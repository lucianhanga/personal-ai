"""Typed multi-agent graph runtime (M8.0, ADR-0011).

A small, hand-rolled state-machine graph over the existing seams: nodes are steps that yield
`AgentEvent`s as the single-agent loop, and a `route` function picks the next node from the shared
`GraphState` (conditional edges) up to a hard step cap. M8.0 ships exactly ONE node — a *responder*
that wraps `run_agent` — so behaviour with the graph enabled equals the single-agent loop. M8.1/M8.2
add planner/researcher/critic/verifier nodes + verification routing **additively** (new nodes, no
runtime change). Nodes call only `ModelProvider` + `ToolGateway` (never bypass the gateway), and the
tenant travels in `GraphState.context` (ADR-0010 / A2) rather than only an ambient contextvar.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from personalai_contracts.ports import AgentContext, ChatMessage, ModelProvider
from personalai_contracts.schemas.tools import Permission
from personalai_core.agent import AgentEvent, run_agent
from personalai_core.gateway import RegisteredTool, ToolGateway


@dataclass
class GraphState:
    """Shared state threaded through graph nodes. Nodes append to ``answer`` / ``data``; ``route``
    reads it to choose the next node. ``context`` carries the tenant (ADR-0010)."""

    context: AgentContext | None = None
    answer: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GraphNode(Protocol):
    """One graph step: yields AgentEvents (and may update ``state``)."""

    name: str

    def run(self, state: GraphState) -> AsyncIterator[AgentEvent]:
        """Run this node, yielding events as they happen."""
        ...


# Given the current state, return the next node name, or None to stop (conditional edges).
Router = Callable[[GraphState], str | None]


@dataclass
class Graph:
    """Runs nodes from ``entry``, following ``route`` after each, bounded by ``max_steps``."""

    nodes: Mapping[str, GraphNode]
    entry: str
    route: Router
    max_steps: int = 8

    async def run(self, state: GraphState) -> AsyncIterator[AgentEvent]:
        current: str | None = self.entry
        steps = 0
        while current is not None and steps < self.max_steps:
            async for ev in self.nodes[current].run(state):
                if ev.type == "answer" and ev.answer:
                    state.answer += ev.answer
                yield ev
            steps += 1
            current = self.route(state)


@dataclass
class _ResponderNode:
    """M8.0 node: the single-agent tool-calling loop as one graph node (== run_agent)."""

    messages: Sequence[ChatMessage]
    provider: ModelProvider
    model: str
    gateway: ToolGateway
    tools: Sequence[RegisteredTool]
    grants: Sequence[Permission]
    approved: bool
    think: bool | None
    max_iterations: int
    name: str = "responder"

    async def run(self, state: GraphState) -> AsyncIterator[AgentEvent]:
        async for ev in run_agent(
            messages=self.messages,
            provider=self.provider,
            model=self.model,
            gateway=self.gateway,
            tools=self.tools,
            grants=self.grants,
            approved=self.approved,
            think=self.think,
            max_iterations=self.max_iterations,
        ):
            yield ev


async def run_graph(
    *,
    messages: Sequence[ChatMessage],
    provider: ModelProvider,
    model: str,
    gateway: ToolGateway,
    tools: Sequence[RegisteredTool],
    grants: Sequence[Permission] = (),
    approved: bool = False,
    max_iterations: int = 8,
    think: bool | None = None,
    context: AgentContext | None = None,
) -> AsyncIterator[AgentEvent]:
    """Drive the M8 typed graph, yielding the same AgentEvents as ``run_agent``.

    M8.0: a single responder node (graph behaviour == single-agent loop). M8.1+ extend the node set
    and ``route`` without changing this entry point.
    """
    responder = _ResponderNode(
        messages=messages,
        provider=provider,
        model=model,
        gateway=gateway,
        tools=tools,
        grants=grants,
        approved=approved,
        think=think,
        max_iterations=max_iterations,
    )
    graph = Graph(
        nodes={responder.name: responder},
        entry=responder.name,
        route=lambda _state: None,  # M8.0: stop after the responder
        max_steps=max_iterations,
    )
    async for ev in graph.run(GraphState(context=context)):
        yield ev
