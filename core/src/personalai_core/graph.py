"""LangGraph agent orchestration runtime (M8, ADR-0012).

LangGraph is the orchestration engine **only** — graph topology, typed shared state, and (from M8.1)
the checkpointer / interrupt-resume. The two privileged capabilities stay on our own seams: graph
nodes call our :class:`ModelProvider` (Ollama / local-first) and our :class:`ToolGateway`
(permissions, egress/SSRF, schema, HIGH-risk approval, audit) **directly**; LangChain's model/tool
abstractions are not adopted. The graph runtime gets no model or tool privileges of its own
(ADR-0012 load-bearing invariant). Because LangGraph nodes are plain async functions, honouring the
invariant is essentially free.

M8.0-lg ships exactly ONE node — a *responder* that runs the single-agent loop (:func:`run_agent`)
and streams its :class:`AgentEvent`s via LangGraph custom streaming — so behaviour with the graph on
equals the single-agent loop. M8.1+ add planner/researcher/critic/verifier nodes and
conditional edges (the accuracy ladder) **additively**, plus the tenant-scoped checkpointer, without
changing this entry point. Keeping :func:`run_graph`'s signature stable is the contract that
``apps/backend/.../turn.py`` and the SSE mapping rely on.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from personalai_contracts.ports import AgentContext, ChatMessage, ModelProvider
from personalai_contracts.schemas.tools import Permission
from personalai_core.agent import AgentEvent, run_agent
from personalai_core.gateway import RegisteredTool, ToolGateway


class GraphState(TypedDict, total=False):
    """Typed shared state threaded through the LangGraph graph. ``context`` carries the tenant
    (ADR-0010 / A2) so nodes never rely solely on an ambient contextvar. M8.1 extends this with the
    accumulated answer/critique/verification state that the checkpointer persists."""

    context: AgentContext | None


def _build_responder_graph(
    *,
    messages: Sequence[ChatMessage],
    provider: ModelProvider,
    model: str,
    gateway: ToolGateway,
    tools: Sequence[RegisteredTool],
    grants: Sequence[Permission],
    approved: bool,
    think: bool | None,
    max_iterations: int,
) -> Any:
    """Compile the M8.0-lg single-responder graph (behaviour == :func:`run_agent`)."""

    async def responder(state: GraphState) -> dict[str, Any]:
        # The single-agent tool-calling loop as one graph node. It calls ONLY the seams (provider +
        # gateway, via run_agent); each AgentEvent is streamed out immediately through LangGraph's
        # custom-stream writer so ordering/streaming to the SSE layer is unchanged.
        writer = get_stream_writer()
        async for ev in run_agent(
            messages=messages,
            provider=provider,
            model=model,
            gateway=gateway,
            tools=tools,
            grants=grants,
            approved=approved,
            think=think,
            max_iterations=max_iterations,
        ):
            writer(ev)
        return {}

    builder = StateGraph(GraphState)
    builder.add_node("responder", responder)
    builder.add_edge(START, "responder")
    builder.add_edge("responder", END)
    return builder.compile()


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
    """Drive the LangGraph agent graph, yielding the same :class:`AgentEvent`s as :func:`run_agent`.

    M8.0-lg: a single responder node (graph behaviour == single-agent loop). M8.1+ extend the node
    set + conditional edges (and add the tenant-scoped checkpointer) without changing this entry
    point.
    """
    graph = _build_responder_graph(
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
    initial: GraphState = {"context": context}
    # custom-stream payloads are exactly the AgentEvents the responder wrote, in order.
    async for ev in graph.astream(initial, stream_mode="custom"):
        yield ev
