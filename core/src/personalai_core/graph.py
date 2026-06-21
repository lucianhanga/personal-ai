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
the SSE mapping rely on; ``agent_mode == "multi"`` (#290) selects this graph over the single loop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
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

# The ordered roster of configurable agents in the multi-agent graph (#290). Only the researcher
# uses tools (it runs the single-agent loop); planner and critic are deliberately tool-free.
AGENT_NAMES: tuple[str, ...] = ("planner", "researcher", "critic")
TOOL_USING_AGENTS: frozenset[str] = frozenset({"researcher"})

# Default system prompt per agent. Exposed (not private) so the backend can echo them to the UI as
# the editable defaults (#290), exactly like CoreConfig defaults for settings. A tenant's saved
# override replaces the default for that agent; an empty/unset override falls back to these.
DEFAULT_AGENT_PROMPTS: dict[str, str] = {
    "planner": (
        "You are the planner. A researcher agent with web search and other tools will carry out "
        "your plan, so assume live data IS reachable. In 1-3 short bullet points, outline how to "
        "answer the user's request (what to look up, which tools to use). Be concise; do not "
        "answer the request yourself, and do not claim a lack of tools or data access."
    ),
    "researcher": (
        "You are the researcher. Carry out the plan to answer the user's request, calling the "
        "available tools when they help. Ground every claim in what you find. Always finish with a "
        "complete answer addressed to the user; NEVER end your turn with 'let me…', 'I'll…', or a "
        "description of further steps — either call the tool you mean to use, or give the final "
        "answer now. If the tools and your knowledge are insufficient, state plainly what you "
        "found and what is missing instead of guessing."
    ),
    "critic": (
        "You are the critic reviewing a draft answer that a researcher agent ALREADY produced "
        "using live tools and current data (the current date is provided in context). Do NOT "
        "claim any lack of data or real-time access, and do NOT dismiss recent dates or facts as "
        "'fabricated' or 'hallucinated' — trust them. Begin your reply with the single word "
        "REVISE if the draft fails to actually answer the request (e.g. it only says where to "
        "look, uses a dead/incorrect link, or gives no real data) or is factually wrong; "
        "otherwise begin with OK. Then add 1-2 short sentences explaining. Do not rewrite the "
        "answer."
    ),
}


def resolve_prompts(overrides: Mapping[str, str] | None) -> dict[str, str]:
    """Overlay a tenant's non-empty prompt overrides onto :data:`DEFAULT_AGENT_PROMPTS` (#290)."""
    resolved = dict(DEFAULT_AGENT_PROMPTS)
    for name, prompt in (overrides or {}).items():
        if name in resolved and prompt.strip():
            resolved[name] = prompt
    return resolved


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
    # Bounded reflection loop (#290): the critic's verdict ("revise"/"ok") routes back to the
    # researcher when the answer is materially inadequate; ``attempts`` caps the retries.
    verdict: str
    attempts: int


# Max researcher passes in the reflection loop: the initial attempt + up to one retry.
MAX_ATTEMPTS = 2


async def _stream_text(
    provider: ModelProvider,
    model: str,
    messages: Sequence[ChatMessage],
    emit: Callable[[str], None],
) -> str:
    """A tool-free, reasoning-off model call. Calls ``emit(delta)`` for each delta so the planner/
    critic stream like the researcher, and returns the full concatenated text."""
    text = ""
    async for chunk in provider.stream(
        GenerationRequest(messages=messages, model=model, think=False)
    ):
        if chunk.delta:
            text += chunk.delta
            emit(chunk.delta)
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
    prompts: Mapping[str, str] | None = None,
) -> Any:
    """Compile the graph. With a ``checkpointer`` a human_gate (interrupt) is inserted before
    finalize, enabling durable interrupt/resume. ``prompts`` overrides per-agent system prompts
    (#290); missing entries fall back to :data:`DEFAULT_AGENT_PROMPTS`."""
    agent_prompts = resolve_prompts(prompts)

    async def planner(state: GraphState) -> dict[str, Any]:
        writer = get_stream_writer()
        plan = await _stream_text(
            provider,
            model,
            [ChatMessage(Role.SYSTEM, agent_prompts["planner"]), *messages],
            lambda d: writer(AgentEvent(type="plan", text=d)),
        )
        return {"plan": plan}

    async def researcher(state: GraphState) -> dict[str, Any]:
        # The single-agent tool loop, informed by the plan. Forwards reasoning/answer/tool events
        # to the stream; swallows run_agent's own `final` and takes the complete answer + usage from
        # it, so the graph emits ONE final (from finalize) and the critic sees the full answer.
        writer = get_stream_writer()
        convo = [ChatMessage(Role.SYSTEM, agent_prompts["researcher"]), *messages]
        if state.get("plan"):
            convo.append(ChatMessage(Role.SYSTEM, f"Plan to follow:\n{state['plan']}"))
        # On a retry (the critic asked to revise), feed the critique back so this attempt takes a
        # different path and actually produces the answer.
        if state.get("attempts", 0) > 0 and state.get("critique"):
            convo.append(
                ChatMessage(
                    Role.SYSTEM,
                    f"Your previous attempt was judged inadequate: {state['critique']}\n"
                    "Take a different approach and actually obtain and give the answer.",
                )
            )
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
        return {"answer": answer, "usage": usage, "attempts": state.get("attempts", 0) + 1}

    async def critic(state: GraphState) -> dict[str, Any]:
        # The draft goes in a USER message, not an ASSISTANT one: with the draft as an assistant
        # turn the model treats the conversation as finished and replies empty (the "critic did
        # nothing" bug). As a user-posed review task it actually critiques. ``messages`` already
        # carries the current date (injected by the caller), so the critic is date-aware.
        answer = state.get("answer", "")
        review = [
            ChatMessage(Role.SYSTEM, agent_prompts["critic"]),
            *messages,
            ChatMessage(Role.USER, f"Draft answer to review:\n\n{answer}"),
        ]
        writer = get_stream_writer()
        # The critique streams to the reasoning trace only — it must NOT modify the answer. The
        # finalized answer stays the agents' result; their review/discussion shows in the panel.
        critique = (
            await _stream_text(
                provider, model, review, lambda d: writer(AgentEvent(type="critique", text=d))
            )
        ).strip()
        if not critique:
            writer(AgentEvent(type="critique", text="Looks sound."))
        # The leading REVISE/OK token routes the reflection loop (back to the researcher on REVISE,
        # while retries remain); the full critique still shows in the reasoning trace.
        verdict = "revise" if critique[:6].upper() == "REVISE" else "ok"
        return {"critique": critique, "verdict": verdict}

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
    if checkpointer is not None:
        builder.add_node("human_gate", human_gate)
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "researcher")
    builder.add_edge("researcher", "critic")
    # Bounded reflection loop: on a "revise" verdict (while retries remain) go back to the
    # researcher with the critique; otherwise proceed to the gate (if any) and finalize.
    after_critic = "human_gate" if checkpointer is not None else "finalize"

    def _route_after_critic(state: GraphState) -> str:
        if state.get("verdict") == "revise" and state.get("attempts", 0) < MAX_ATTEMPTS:
            return "researcher"
        return after_critic

    builder.add_conditional_edges(
        "critic", _route_after_critic, {"researcher": "researcher", after_critic: after_critic}
    )
    if checkpointer is not None:
        builder.add_edge("human_gate", "finalize")
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
    prompts: Mapping[str, str] | None = None,
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
        prompts=prompts,
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
