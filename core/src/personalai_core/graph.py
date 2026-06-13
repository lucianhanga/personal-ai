"""LangGraph agent orchestration runtime (M8, ADR-0012).

LangGraph is the orchestration engine **only** — graph topology, typed shared state, the
checkpointer, and the durable interrupt/resume human gate. The two privileged capabilities stay on
our own seams: graph nodes call our :class:`ModelProvider` (Ollama / local-first) and our
:class:`ToolGateway` (permissions, egress/SSRF, schema, HIGH-risk approval, audit) **directly**;
LangChain's model/tool abstractions are not adopted. The graph runtime gets no model or tool
privileges of its own (ADR-0012 load-bearing invariant).

Topology: **planner -> researcher -> critic -> [human_gate] -> finalize -> END**.
- planner: one tool-free model call producing a short plan; emits a ``plan`` step.
- researcher: the single-agent tool loop (:func:`run_agent`) informed by the plan; streams
  reasoning/answer/tool steps; takes the full answer + usage from run_agent's own final.
- critic: one model call reviewing the answer; emits a ``critique`` step.
- human_gate (only when a ``checkpointer`` is supplied, M8.1c): LangGraph ``interrupt()`` suspends
  the run for human approval; the durable checkpoint lets it resume later (tenant-scoped in prod).
- finalize: emits the single terminal ``final``.

Keeping :func:`run_graph`'s signature stable is the contract that ``apps/backend/.../turn.py`` and
the SSE mapping rely on; the ``agent_graph_enabled`` flag selects this graph over the single loop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
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
    usage to the terminal ``final`` event; ``decision`` is the human gate's resume value."""

    context: AgentContext | None
    plan: str
    answer: str
    critique: str
    usage: dict[str, int]
    decision: str


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
    checkpointer: BaseCheckpointSaver[Any] | None,
) -> Any:
    """Compile the graph. With a ``checkpointer`` a human_gate (interrupt) is inserted before
    finalize, enabling durable interrupt/resume."""

    async def planner(state: GraphState) -> dict[str, Any]:
        plan = await _generate_text(
            provider, model, [ChatMessage(Role.SYSTEM, _PLANNER_PROMPT), *messages]
        )
        get_stream_writer()(AgentEvent(type="plan", text=plan))
        return {"plan": plan}

    async def researcher(state: GraphState) -> dict[str, Any]:
        # The single-agent tool loop, informed by the plan. Forwards reasoning/answer/tool events
        # to the stream; swallows run_agent's own `final` and takes the complete answer + usage from
        # it, so the graph emits ONE final (from finalize) and the critic sees the full answer.
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
        review = [
            ChatMessage(Role.SYSTEM, _CRITIC_PROMPT),
            *messages,
            ChatMessage(Role.ASSISTANT, state.get("answer", "")),
        ]
        critique = await _generate_text(provider, model, review)
        get_stream_writer()(AgentEvent(type="critique", text=critique))
        return {"critique": critique}

    async def human_gate(state: GraphState) -> dict[str, Any]:
        # Durable suspend: interrupt() raises on the first pass (checkpoint persisted) and returns
        # the resume value on the second. The payload is what the human is approving.
        decision = interrupt(
            {
                "reason": "approve_answer",
                "answer": state.get("answer", ""),
                "critique": state.get("critique", ""),
            }
        )
        return {"decision": str(decision)}

    async def finalize(state: GraphState) -> dict[str, Any]:
        get_stream_writer()(
            AgentEvent(type="final", answer=state.get("answer", ""), usage=state.get("usage", {}))
        )
        return {}

    builder = StateGraph(GraphState)
    builder.add_node("planner", planner)
    builder.add_node("researcher", researcher)
    builder.add_node("critic", critic)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "researcher")
    builder.add_edge("researcher", "critic")
    if checkpointer is not None:
        builder.add_node("human_gate", human_gate)
        builder.add_edge("critic", "human_gate")
        builder.add_edge("human_gate", "finalize")
    else:
        builder.add_edge("critic", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


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
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    thread_id: str | None = None,
    resume: Any | None = None,
) -> AsyncIterator[AgentEvent]:
    """Drive the LangGraph agent graph, yielding ordered :class:`AgentEvent`s.

    Without a ``checkpointer``: planner -> researcher -> critic -> finalize (plan, answer/tool
    steps, critique, final). With a ``checkpointer`` (+ ``thread_id``) the durable human gate is
    active: the first run suspends at the gate and yields an ``approval_request`` (no final);
    calling again with ``resume`` continues to the final. Cross-tenant isolation is enforced by the
    (tenant-bound) checkpointer in production.
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
        checkpointer=checkpointer,
    )
    if checkpointer is None:
        async for ev in graph.astream({"context": context}, stream_mode="custom"):
            yield ev
        return

    config = {"configurable": {"thread_id": thread_id}}
    graph_input: Any = Command(resume=resume) if resume is not None else {"context": context}
    async for ev in graph.astream(graph_input, config, stream_mode="custom"):
        yield ev
    snapshot = await graph.aget_state(config)
    if snapshot.interrupts:
        # Suspended at the human gate: surface the approval request (run is durably checkpointed).
        yield AgentEvent(type="approval_request", output=dict(snapshot.interrupts[0].value))
