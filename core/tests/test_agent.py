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
    assert kinds == ["tool_call", "tool_result", "final"]
    assert events[0].tool == "calculator"
    assert events[1].ok is True and events[1].output == {"result": 437}
    assert events[2].answer == "The answer is 437."


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
    assert [e.type for e in events] == ["final"]
    assert events[0].answer == "echo: hi"


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


def test_agent_stops_at_iteration_cap() -> None:
    class _Loopy(FakeModelProvider):
        async def generate(self, request: GenerationRequest) -> GenerationResult:
            return GenerationResult(
                text="thinking",
                model=request.model,
                tool_calls=[ToolCallRequest(name="calculator", arguments={})],
            )

    async def _run() -> list[AgentEvent]:
        return [
            ev
            async for ev in run_agent(
                messages=[ChatMessage(Role.USER, "go")],
                provider=_Loopy(),
                model="m",
                gateway=_gateway(),
                tools=[RegisteredTool(CALC, _Calc())],
                max_iterations=2,
            )
        ]

    events = asyncio.run(_run())
    assert events[-1].type == "final"  # bailed out with the last text after the cap
    assert events[-1].answer == "thinking"
