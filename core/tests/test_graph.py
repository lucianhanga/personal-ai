"""M8.0 typed-graph runtime: the responder graph equals the single-agent loop, and the runner
routes through nodes + honors the step cap."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from personalai_contracts.ports import ChatMessage, Role
from personalai_contracts.testing import FakeModelProvider
from personalai_core import (
    AgentEvent,
    Graph,
    GraphState,
    InProcessExecutor,
    Registry,
    ToolGateway,
    run_graph,
)
from personalai_core.gateway import RegisteredTool
from personalai_core.security import AuditLog


def _gateway() -> ToolGateway:
    reg: Registry[RegisteredTool] = Registry("tool")
    return ToolGateway(reg, InProcessExecutor(), audit=AuditLog(), egress_check=lambda h: None)


def test_run_graph_equals_single_agent_loop_no_tools() -> None:
    # M8.0: the single-responder graph yields exactly what run_agent does.
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


@dataclass
class _SayNode:
    name: str
    text: str

    async def run(self, state: GraphState) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(type="answer", answer=self.text)


def test_graph_runner_routes_through_nodes_and_accumulates_answer() -> None:
    def route(state: GraphState) -> str | None:
        # a -> b -> stop
        if state.data.get("went_b"):
            return None
        state.data["went_b"] = True
        return "b"

    graph = Graph(
        nodes={"a": _SayNode("a", "A "), "b": _SayNode("b", "B")},
        entry="a",
        route=route,
    )

    async def _run() -> GraphState:
        state = GraphState()
        async for _ in graph.run(state):
            pass
        return state

    state = asyncio.run(_run())
    assert state.answer == "A B"  # both nodes ran, in order; answer accumulated


def test_graph_runner_honors_step_cap() -> None:
    # A router that never stops must still terminate at max_steps.
    graph = Graph(nodes={"a": _SayNode("a", "x")}, entry="a", route=lambda _s: "a", max_steps=3)

    async def _run() -> list[AgentEvent]:
        return [ev async for ev in graph.run(GraphState())]

    events = asyncio.run(_run())
    assert len(events) == 3  # capped at max_steps, not infinite
