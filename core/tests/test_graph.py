"""M8.1b/c multi-node LangGraph graph: planner -> researcher -> critic -> [human_gate] -> finalize.

The graph streams ordered AgentEvents (plan, the researcher's reasoning/answer/tool steps, critique,
then a single final). With a checkpointer the durable human gate suspends before finalize and
resumes later. Nodes call only our ModelProvider + ToolGateway seams (ADR-0012)."""

from __future__ import annotations

import asyncio

from langgraph.checkpoint.memory import InMemorySaver

from personalai_contracts.ports import (
    ChatMessage,
    GenerationRequest,
    GenerationResult,
    Role,
    ToolCall,
    ToolCallRequest,
    ToolResult,
)
from personalai_contracts.schemas.tools import Provenance, RiskLevel, ToolManifest
from personalai_contracts.testing import FakeModelProvider
from personalai_core import AgentEvent, InProcessExecutor, Registry, ToolGateway, run_graph
from personalai_core.gateway import RegisteredTool
from personalai_core.security.audit import AuditLog

ECHO = ToolManifest(
    name="echo",
    version="1.0.0",
    provenance=Provenance(maintainer="tests"),
    description="echo",
    risk=RiskLevel.LOW,
)


class _Echo:
    name = "echo"

    async def invoke(self, call: ToolCall) -> ToolResult:
        return ToolResult(ok=True, output={"echoed": True})


def _gateway(tools: list[RegisteredTool] | None = None) -> ToolGateway:
    reg: Registry[RegisteredTool] = Registry("tool")
    for rt in tools or []:
        reg.register(rt.manifest.name, rt)
    return ToolGateway(reg, InProcessExecutor(), audit=AuditLog(), egress_check=lambda h: None)


def _drain(**kwargs: object) -> list[AgentEvent]:
    async def _run() -> list[AgentEvent]:
        return [ev async for ev in run_graph(**kwargs)]  # type: ignore[arg-type]

    return asyncio.run(_run())


def test_planner_researcher_critic_pipeline() -> None:
    # FakeModelProvider echoes the last message, so every node produces non-empty text.
    events = _drain(
        messages=[ChatMessage(Role.USER, "hi")],
        provider=FakeModelProvider(),
        model="m",
        gateway=_gateway(),
        tools=[],
    )
    assert [e.type for e in events] == ["plan", "answer", "critique", "final"]
    assert events[0].text  # planner produced a plan
    assert events[2].text  # critic produced a critique
    # The final answer is the researcher's streamed answer (echo of the plan-augmented prompt).
    assert events[1].answer


class _Empty(FakeModelProvider):
    """Every call returns empty text -> empty plan (researcher skips plan injection)."""

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(text="", model=request.model)


def test_empty_plan_skips_injection_and_streams_no_answer() -> None:
    events = _drain(
        messages=[ChatMessage(Role.USER, "hi")],
        provider=_Empty(),
        model="m",
        gateway=_gateway(),
        tools=[],
    )
    # No answer delta (empty), but plan + critique steps + the terminal final still flow.
    assert [e.type for e in events] == ["plan", "critique", "final"]
    assert events[0].text == ""
    assert events[-1].usage == {}


class _ToolThenAnswer(FakeModelProvider):
    """Researcher turn 1: a tool call; turn 2: a final answer with usage."""

    def __init__(self) -> None:
        super().__init__(name="scripted")
        self._n = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        # Planner/critic calls have no tools; only the researcher offers tools.
        if request.tools:
            self._n += 1
            if self._n == 1:
                return GenerationResult(
                    text="",
                    model=request.model,
                    tool_calls=[ToolCallRequest(name="echo", arguments={"v": 1})],
                )
            return GenerationResult(text="done", model=request.model, usage={"total_tokens": 7})
        return GenerationResult(text="plan/critique", model=request.model)


def test_researcher_tool_steps_flow_and_usage_reaches_final() -> None:
    tool = RegisteredTool(ECHO, _Echo())
    events = _drain(
        messages=[ChatMessage(Role.USER, "use a tool")],
        provider=_ToolThenAnswer(),
        model="m",
        gateway=_gateway([tool]),
        tools=[tool],
        approved=True,
        max_iterations=4,
    )
    kinds = [e.type for e in events]
    assert kinds == ["plan", "tool_call", "tool_result", "answer", "critique", "final"]
    assert events[1].tool == "echo"
    assert events[2].ok is True
    assert events[-1].usage == {"total_tokens": 7}  # usage from run_agent's final reaches the end


class _Recorder(FakeModelProvider):
    """Records the system prompts each node sends, to assert prompt overrides reach the nodes."""

    def __init__(self) -> None:
        super().__init__(name="rec")
        self.system_prompts: list[str] = []

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.system_prompts += [m.content for m in request.messages if m.role == Role.SYSTEM]
        return GenerationResult(text="ok", model=request.model)


def test_prompt_overrides_reach_planner_and_critic() -> None:
    # #290: per-agent prompt overrides replace the defaults in the planner/critic (and researcher).
    rec = _Recorder()
    _drain(
        messages=[ChatMessage(Role.USER, "hi")],
        provider=rec,
        model="m",
        gateway=_gateway(),
        tools=[],
        prompts={"planner": "CUSTOM PLANNER", "critic": "CUSTOM CRITIC"},
    )
    assert any("CUSTOM PLANNER" in s for s in rec.system_prompts)
    assert any("CUSTOM CRITIC" in s for s in rec.system_prompts)
    # An unset agent (researcher) still gets its built-in default prompt.
    assert any("You are the researcher" in s for s in rec.system_prompts)


def test_human_gate_suspends_then_resumes_durably() -> None:
    # M8.1c: with a checkpointer the graph suspends at the human gate (approval_request, no final);
    # resuming on the SAME checkpointer continues to the final (durable interrupt/resume).
    saver = InMemorySaver()
    common: dict[str, object] = {
        "messages": [ChatMessage(Role.USER, "hi")],
        "provider": FakeModelProvider(),
        "model": "m",
        "gateway": _gateway(),
        "tools": [],
        "checkpointer": saver,
        "thread_id": "run-1",
    }

    first = _drain(**common)
    assert [e.type for e in first] == ["plan", "answer", "critique", "approval_request"]
    assert first[-1].output is not None
    assert first[-1].output["reason"] == "approve_answer"

    # Resume with the human's decision -> finalize emits the single final; no second approval.
    second = _drain(**common, resume="approve")
    assert [e.type for e in second] == ["final"]
    assert second[0].answer
