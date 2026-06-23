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
from personalai_core.graph import MAX_ATTEMPTS
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
    # An empty planner streams nothing (no plan step); the critic falls back to "Looks sound.",
    # and the terminal final still flows.
    assert [e.type for e in events] == ["critique", "final"]
    assert events[0].text == "Looks sound."
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


class _ToolThenRecord(FakeModelProvider):
    """Researcher calls a tool then answers; records every node's system prompts so we can assert
    the critic sees the retrieved tool output as ground-truth evidence."""

    def __init__(self) -> None:
        super().__init__(name="rec2")
        self._n = 0
        self.system_prompts: list[str] = []

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.system_prompts += [m.content for m in request.messages if m.role == Role.SYSTEM]
        if request.tools:
            self._n += 1
            if self._n == 1:
                return GenerationResult(
                    text="",
                    model=request.model,
                    tool_calls=[ToolCallRequest(name="echo", arguments={"v": 1})],
                )
            return GenerationResult(text="done", model=request.model)
        return GenerationResult(text="OK looks fine", model=request.model)


def test_critic_receives_the_researchers_evidence_as_ground_truth() -> None:
    # The critic judges against the actual tool output, not its own (stale) knowledge — so the
    # researcher's retrieved evidence must reach the critic's context.
    tool = RegisteredTool(ECHO, _Echo())
    prov = _ToolThenRecord()
    _drain(
        messages=[ChatMessage(Role.USER, "use a tool")],
        provider=prov,
        model="m",
        gateway=_gateway([tool]),
        tools=[tool],
        approved=True,
        max_iterations=4,
    )
    assert any("Sources the researcher retrieved" in s for s in prov.system_prompts)
    assert any("echoed" in s for s in prov.system_prompts)  # the real tool result, not a name


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


class _CriticRevises(FakeModelProvider):
    """Researcher gives a wrong answer; the critic flags it (its review sees 'Draft answer')."""

    def __init__(self) -> None:
        super().__init__(name="rev")

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        last = request.messages[-1].content if request.messages else ""
        if "Draft answer to review" in last:
            return GenerationResult(
                text="REVISE: the capital is Canberra, not Sydney.", model=request.model
            )
        return GenerationResult(text="The capital of Australia is Sydney.", model=request.model)


class _ReviseThenAccept(FakeModelProvider):
    """A weak first answer the critic REVISEs, then an improved retry the critic accepts (OK)."""

    def __init__(self) -> None:
        super().__init__(name="loop")
        self.researcher_runs = 0
        self.critic_runs = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        sys_text = " ".join(m.content for m in request.messages if m.role == Role.SYSTEM)
        last = request.messages[-1].content if request.messages else ""
        if "Draft answer to review" in last:
            self.critic_runs += 1
            text = "REVISE: only a link, no data." if self.critic_runs == 1 else "OK: looks good."
            return GenerationResult(text=text, model=request.model)
        if "You are the planner" in sys_text:
            return GenerationResult(text="search for it", model=request.model)
        self.researcher_runs += 1
        text = "See the website." if self.researcher_runs == 1 else "It is 23C and sunny."
        return GenerationResult(text=text, model=request.model)


def test_reflection_loop_retries_on_revise_then_finalizes_the_improved_answer() -> None:
    # #290 bounded reflection loop: a "REVISE" verdict sends the researcher back once (with the
    # critique as feedback); the improved retry is accepted and finalized.
    provider = _ReviseThenAccept()
    events = _drain(
        messages=[ChatMessage(Role.USER, "weather?")],
        provider=provider,
        model="m",
        gateway=_gateway(),
        tools=[],
    )
    assert provider.researcher_runs == 2  # initial + one retry
    assert provider.critic_runs == 2  # reviewed both attempts
    final = next(e for e in events if e.type == "final")
    assert final.answer == "It is 23C and sunny."  # the improved retry, not the weak first draft


class _VerifierProvider(FakeModelProvider):
    """Drives the verifier: critic OK (no reflection retry), then the judge returns a verdict.
    First judge verdict is 'fail' (one researcher retry), second is 'pass' (finalize)."""

    def __init__(self, judge_first: str = "fail") -> None:
        super().__init__(name="verify")
        self.researcher_runs = 0
        self.judge_runs = 0
        self._judge_first = judge_first

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        sys_text = " ".join(m.content for m in request.messages if m.role == Role.SYSTEM)
        last = request.messages[-1].content if request.messages else ""
        if "You are the verifier" in sys_text or "Draft answer to verify" in last:
            self.judge_runs += 1
            v = self._judge_first if self.judge_runs == 1 else "pass"
            body = f'{{"verdict": "{v}", "reason": "r"}}'
            return GenerationResult(text=body, model=request.model)
        if "Draft answer to review" in last:
            return GenerationResult(text="OK: fine", model=request.model)  # critic: no reflection
        if "You are the planner" in sys_text:
            return GenerationResult(text="plan", model=request.model)
        self.researcher_runs += 1
        return GenerationResult(text=f"answer {self.researcher_runs}", model=request.model)


def test_standard_mode_skips_the_verifier() -> None:
    provider = _VerifierProvider()
    events = _drain(
        messages=[ChatMessage(Role.USER, "q")],
        provider=provider,
        model="m",
        gateway=_gateway(),
        tools=[],
        accuracy_mode="standard",
    )
    assert not any(e.type == "verification" for e in events)  # no judge in standard mode
    assert provider.judge_runs == 0


def test_accurate_mode_runs_the_verifier_and_retries_on_fail() -> None:
    provider = _VerifierProvider(judge_first="fail")
    events = _drain(
        messages=[ChatMessage(Role.USER, "q")],
        provider=provider,
        model="m",
        gateway=_gateway(),
        tools=[],
        accuracy_mode="accurate",
    )
    verifications = [e for e in events if e.type == "verification"]
    assert verifications  # the judge ran (accurate mode)
    assert verifications[0].verdict == "fail"
    assert provider.researcher_runs == 2  # one retry triggered by the verifier
    assert any(e.type == "final" for e in events)


def test_reflection_loop_is_bounded() -> None:
    # If the critic always says REVISE, the loop still stops at MAX_ATTEMPTS researcher passes.
    provider = _CriticRevises()  # always REVISE
    events = _drain(
        messages=[ChatMessage(Role.USER, "capital of australia?")],
        provider=provider,
        model="m",
        gateway=_gateway(),
        tools=[],
    )
    # Exactly MAX_ATTEMPTS researcher passes -> two "answer" deltas precede the terminal final.
    assert sum(1 for e in events if e.type == "answer") == MAX_ATTEMPTS
    assert any(e.type == "final" for e in events)


def test_critic_review_goes_to_the_trace_not_the_answer() -> None:
    # #290: the critic's review is a critique step (reasoning panel) and must NOT modify the answer:
    # only the agents' final result is shown; their discussion stays in the trace.
    events = _drain(
        messages=[ChatMessage(Role.USER, "capital of australia?")],
        provider=_CriticRevises(),
        model="m",
        gateway=_gateway(),
        tools=[],
    )
    critique = next(e for e in events if e.type == "critique")
    assert "Canberra" in (critique.text or "")
    # No "Reviewer" note leaks into the answer stream.
    assert not any("Reviewer" in (e.answer or "") for e in events if e.type == "answer")
    # The terminal answer is the researcher's answer, unchanged by the critic.
    final = next(e for e in events if e.type == "final")
    assert final.answer == "The capital of Australia is Sydney."


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
