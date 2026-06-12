"""M8.0-lg LangGraph runtime: the single responder graph equals the single-agent loop, and the
custom-stream surface yields the same ordered AgentEvents (reasoning/tool/answer/final) as
``run_agent`` (ADR-0012)."""

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


def test_run_graph_equals_single_agent_loop_no_tools() -> None:
    # M8.0-lg: the single-responder LangGraph graph yields exactly what run_agent does.
    async def _run() -> list[AgentEvent]:
        return [
            ev
            async for ev in run_graph(
                messages=[ChatMessage(Role.USER, "hi")],
                provider=FakeModelProvider(),
                model="m",
                gateway=_gateway(),
                tools=[],
            )
        ]

    events = asyncio.run(_run())
    assert [e.type for e in events] == ["answer", "final"]
    assert events[0].answer == "echo: hi"
    assert events[-1].answer == "echo: hi"


class _ToolThenAnswer(FakeModelProvider):
    """Turn 1: reasoning + a tool call; turn 2: a plain answer with usage."""

    def __init__(self) -> None:
        super().__init__(name="scripted")
        self._n = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self._n += 1
        if self._n == 1:
            return GenerationResult(
                text="",
                model=request.model,
                thinking="deciding",
                tool_calls=[ToolCallRequest(name="echo", arguments={"v": 1})],
            )
        return GenerationResult(text="done", model=request.model, usage={"total_tokens": 7})


def test_run_graph_streams_all_event_kinds_through_the_graph() -> None:
    # The LangGraph custom-stream surface carries reasoning, tool_call, tool_result, answer and
    # final in order, identical to the single-agent loop.
    tool = RegisteredTool(ECHO, _Echo())

    async def _run() -> list[AgentEvent]:
        return [
            ev
            async for ev in run_graph(
                messages=[ChatMessage(Role.USER, "use a tool")],
                provider=_ToolThenAnswer(),
                model="m",
                gateway=_gateway([tool]),
                tools=[tool],
                approved=True,
                max_iterations=4,
                think=True,
            )
        ]

    events = asyncio.run(_run())
    kinds = [e.type for e in events]
    assert kinds == ["reasoning", "tool_call", "tool_result", "answer", "final"]
    assert events[1].tool == "echo"
    assert events[2].ok is True
    assert events[-1].usage == {"total_tokens": 7}
