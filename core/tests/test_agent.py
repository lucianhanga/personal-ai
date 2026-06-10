"""Single-agent tool-calling loop (fakes only)."""

from __future__ import annotations

import asyncio

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
from personalai_core import InProcessExecutor, RegisteredTool, Registry, ToolGateway, run_agent
from personalai_core.agent import AgentEvent
from personalai_core.security.audit import AuditLog

CALC = ToolManifest(
    name="calculator",
    version="1.0.0",
    provenance=Provenance(maintainer="tests"),
    description="math",
    risk=RiskLevel.LOW,
)


class _Calc:
    name = "calculator"

    async def invoke(self, call: ToolCall) -> ToolResult:
        return ToolResult(ok=True, output={"result": 437})


class _Scripted(FakeModelProvider):
    """First turn asks for the calculator; after seeing results, gives a final answer."""

    def __init__(self) -> None:
        super().__init__(name="scripted")
        self._n = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self._n += 1
        if self._n == 1:
            return GenerationResult(
                text="",
                model=request.model,
                tool_calls=[ToolCallRequest(name="calculator", arguments={"expression": "23*19"})],
            )
        return GenerationResult(text="The answer is 437.", model=request.model)


def _gateway() -> ToolGateway:
    reg: Registry[RegisteredTool] = Registry("tool")
    reg.register("calculator", RegisteredTool(CALC, _Calc()))
    return ToolGateway(reg, InProcessExecutor(), audit=AuditLog(), egress_check=lambda h: None)


def test_agent_calls_tool_then_answers() -> None:
    async def _run() -> list[AgentEvent]:
        gw = _gateway()
        tools = [RegisteredTool(CALC, _Calc())]
        return [
            ev
            async for ev in run_agent(
                messages=[ChatMessage(Role.USER, "what is 23*19?")],
                provider=_Scripted(),
                model="m",
                gateway=gw,
                tools=tools,
            )
        ]

    events = asyncio.run(_run())
    kinds = [e.type for e in events]
    # tool turn first (no answer text), then the streamed answer, then final.
    assert kinds == ["tool_call", "tool_result", "answer", "final"]
    assert events[0].tool == "calculator"
    assert events[1].ok is True and events[1].output == {"result": 437}
    # The answer streams as "answer" deltas and is repeated on the final event.
    answer = "".join(e.answer or "" for e in events if e.type == "answer")
    assert answer == "The answer is 437."
    assert events[-1].answer == "The answer is 437."


def test_agent_answers_directly_without_tools() -> None:
    async def _run() -> list[AgentEvent]:
        return [
            ev
            async for ev in run_agent(
                messages=[ChatMessage(Role.USER, "hi")],
                provider=FakeModelProvider(),
                model="m",
                gateway=_gateway(),
                tools=[RegisteredTool(CALC, _Calc())],
            )
        ]

    events = asyncio.run(_run())
    assert [e.type for e in events] == ["answer", "final"]  # answer streamed, then final
    assert events[0].answer == "echo: hi"
    assert events[-1].answer == "echo: hi"


def test_agent_surfaces_reasoning() -> None:
    class _Thinker(FakeModelProvider):
        async def generate(self, request: GenerationRequest) -> GenerationResult:
            return GenerationResult(text="the answer", model=request.model, thinking="step by step")

    async def _run() -> list[AgentEvent]:
        return [
            ev
            async for ev in run_agent(
                messages=[ChatMessage(Role.USER, "why?")],
                provider=_Thinker(),
                model="m",
                gateway=_gateway(),
                tools=[RegisteredTool(CALC, _Calc())],
                think=True,
            )
        ]

    events = asyncio.run(_run())
    # Reasoning is emitted as its own ordered event (before the final answer).
    assert events[0].type == "reasoning"
    assert events[0].thinking == "step by step"
    assert events[-1].type == "final"


def test_agent_forces_answer_after_cap() -> None:
    """At the tool-step cap, a final tools-disabled turn must still produce a streamed answer."""

    class _AlwaysTool(FakeModelProvider):
        async def generate(self, request: GenerationRequest) -> GenerationResult:
            if request.tools:  # budget remains -> keep calling the tool (with some chatter)
                return GenerationResult(
                    text="ok",
                    model=request.model,
                    tool_calls=[ToolCallRequest(name="calculator", arguments={})],
                )
            # forced-final turn (tools disabled) -> synthesize an answer (with reasoning + usage)
            return GenerationResult(
                text="Best answer from what I found.",
                model=request.model,
                thinking="wrapping up",
                usage={"total_tokens": 5},
            )

    async def _run() -> list[AgentEvent]:
        return [
            ev
            async for ev in run_agent(
                messages=[ChatMessage(Role.USER, "go")],
                provider=_AlwaysTool(),
                model="m",
                gateway=_gateway(),
                tools=[RegisteredTool(CALC, _Calc())],
                max_iterations=2,
            )
        ]

    events = asyncio.run(_run())
    assert sum(e.type == "tool_call" for e in events) == 2  # used the whole budget
    answer = "".join(e.answer or "" for e in events if e.type == "answer")
    assert "Best answer from what I found." in answer  # forced-final streamed a real answer
    assert events[-1].type == "final" and events[-1].answer == "Best answer from what I found."
    assert events[-1].usage == {"total_tokens": 5}  # usage from the forced-final turn


def test_tool_output_fed_back_as_untrusted_data() -> None:
    """The model's next turn must see the tool result framed as untrusted DATA (injection guard)."""

    class _Capture(FakeModelProvider):
        def __init__(self) -> None:
            super().__init__(name="cap")
            self._n = 0
            self.seen: list[str] = []

        async def generate(self, request: GenerationRequest) -> GenerationResult:
            self._n += 1
            if self._n == 1:
                return GenerationResult(
                    text="", model=request.model, tool_calls=[ToolCallRequest("calculator", {})]
                )
            self.seen = [m.content for m in request.messages if m.role == Role.TOOL]
            return GenerationResult(text="done", model=request.model)

    provider = _Capture()

    async def _run() -> None:
        async for _ in run_agent(
            messages=[ChatMessage(Role.USER, "go")],
            provider=provider,
            model="m",
            gateway=_gateway(),
            tools=[RegisteredTool(CALC, _Calc())],
        ):
            pass

    asyncio.run(_run())
    assert provider.seen and "untrusted DATA" in provider.seen[0]
    assert "<tool_output>" in provider.seen[0]


def test_large_tool_output_is_truncated() -> None:
    from personalai_core.agent import _tool_payload

    payload = _tool_payload(True, {"content": "x" * 50_000}, None)
    assert len(payload) < 50_000 and "truncated" in payload
    assert len(_tool_payload(True, {"content": "small"}, None)) < 100  # short output untouched
