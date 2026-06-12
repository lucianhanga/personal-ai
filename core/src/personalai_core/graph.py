"""LangGraph agent orchestration runtime (M8, ADR-0012).

LangGraph is the orchestration engine **only** — graph topology, typed shared state, and (from
M8.1c) the checkpointer / interrupt-resume. The two privileged capabilities stay on our own seams:
graph nodes call our :class:`ModelProvider` (Ollama / local-first) and our :class:`ToolGateway`
(permissions, egress/SSRF, schema, HIGH-risk approval, audit) **directly**; LangChain's model/tool
abstractions are not adopted. The graph runtime gets no model or tool privileges of its own
(ADR-0012 load-bearing invariant).

M8.1b ships a typed multi-node graph: **planner -> researcher -> critic -> END**. The planner makes
one tool-free model call producing a short plan; the researcher runs the single-agent tool loop
(:func:`run_agent`) informed by the plan; the critic makes one model call reviewing the answer. The
graph streams the same :class:`AgentEvent`s out via LangGraph custom streaming (plus ``plan`` and
``critique`` steps). Linear for now — the revision loop + durable human gate land with the
verification ladder (M8.1c / M8.2). Keeping :func:`run_graph`'s signature stable is the contract
that ``apps/backend/.../turn.py`` and the SSE mapping rely on; the ``agent_graph_enabled`` flag
selects this graph over the single-agent loop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from personalai_contracts.ports import (
    AgentContext,
    ChatMessage,
    GenerationRequest,
    ModelProvider,
    Role,
)
from personalai_contracts.schemas.tools import Permission
from personalai_core.agent import AgentEvent, run_agent
from personalai_core.gateway import RegisteredTool, ToolGateway

_PLANNER_PROMPT = (
    "You are the planner. In 1-3 short bullet points, outline how to answer the user's request. "
    "Be concise; do not answer the request itself, only plan the approach."
)
_CRITIC_PROMPT = (
    "You are the critic. Briefly review the assistant's answer against the user's request: note "
    "any gaps, errors, or unsupported claims in 1-3 short sentences. Do not rewrite the answer."
)


class GraphState(TypedDict, total=False):
    """Typed shared state threaded through the graph. ``context`` carries the tenant (ADR-0010 /
    A2); ``plan``/``answer``/``critique`` accumulate each node's output; ``usage`` carries token
    usage to the terminal ``final`` event."""

    context: AgentContext | None
    plan: str
    answer: str
    critique: str
    usage: dict[str, int]


async def _generate_text(
    provider: ModelProvider, model: str, messages: Sequence[ChatMessage]
) -> str:
    """One tool-free, reasoning-off model call returning the concatenated answer text."""
    text = ""
    async for chunk in provider.stream(
        GenerationRequest(messages=messages, model=model, think=False)
    ):
        if chunk.delta:
            text += chunk.delta
    return text


def _build_graph(
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
    """Compile the M8.1b planner -> researcher -> critic graph."""

    async def planner(state: GraphState) -> dict[str, Any]:
        plan = await _generate_text(
            provider, model, [ChatMessage(Role.SYSTEM, _PLANNER_PROMPT), *messages]
        )
        get_stream_writer()(AgentEvent(type="plan", text=plan))
        return {"plan": plan}

    async def researcher(state: GraphState) -> dict[str, Any]:
        # The single-agent tool loop, informed by the plan. Forwards reasoning/answer/tool events
        # to the stream; swallows run_agent's own `final` and takes the complete answer + usage from
        # it, so the graph emits ONE final (after the critic) and the critic sees the full answer.
        writer = get_stream_writer()
        convo = list(messages)
        if state.get("plan"):
            convo.append(ChatMessage(Role.SYSTEM, f"Plan to follow:\n{state['plan']}"))
        answer, usage = "", {}
        async for ev in run_agent(
            messages=convo,
            provider=provider,
            model=model,
            gateway=gateway,
            tools=tools,
            grants=grants,
            approved=approved,
            think=think,
            max_iterations=max_iterations,
        ):
            if ev.type == "final":
                answer = ev.answer or ""
                usage = dict(ev.usage or {})
                continue
            writer(ev)
        return {"answer": answer, "usage": usage}

    async def critic(state: GraphState) -> dict[str, Any]:
        writer = get_stream_writer()
        review = [
            ChatMessage(Role.SYSTEM, _CRITIC_PROMPT),
            *messages,
            ChatMessage(Role.ASSISTANT, state.get("answer", "")),
        ]
        critique = await _generate_text(provider, model, review)
        writer(AgentEvent(type="critique", text=critique))
        # Terminal: emit the single final with the turn's usage (answer already streamed).
        writer(
            AgentEvent(type="final", answer=state.get("answer", ""), usage=state.get("usage", {}))
        )
        return {"critique": critique}

    builder = StateGraph(GraphState)
    builder.add_node("planner", planner)
    builder.add_node("researcher", researcher)
    builder.add_node("critic", critic)
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "researcher")
    builder.add_edge("researcher", "critic")
    builder.add_edge("critic", END)
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
    """Drive the LangGraph agent graph, yielding ordered :class:`AgentEvent`s (plan, reasoning,
    answer, tool steps, critique, then a single final).

    M8.1b: planner -> researcher -> critic. M8.1c+ add the durable human gate + conditional revision
    without changing this entry point.
    """
    graph = _build_graph(
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
    async for ev in graph.astream(initial, stream_mode="custom"):
        yield ev
