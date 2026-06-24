"""Chat-turn orchestration, independent of FastAPI (A4/#227).

``run_turn`` drives a single assistant turn — either the multi-step agent loop (tools) or a plain
provider stream — and yields typed ``TurnEvent``s. The HTTP route maps these to SSE frames and owns
persistence; this module owns the orchestration so it is testable with fakes (no TestClient) and is
the seam the M8 typed graph will grow into / replace.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from personalai_contracts.ports import (
    AgentContext,
    ChatMessage,
    GenerationRequest,
    ModelProvider,
    Role,
)
from personalai_core import run_agent, run_graph

# The single-agent loop has no agent persona, so without a nudge the model answers from "head" even
# when a tool would be exact — tools end up enabled but unused (#318). Encourage tool use here; the
# multi-agent researcher already carries its own tool-use prompt, so this stays scoped to single
# mode and is only added when tools are actually offered.
_SINGLE_AGENT_TOOL_PROMPT = (
    "You have tools available. Use them whenever they make the answer more accurate or current — "
    "for exact arithmetic call the calculator; for facts you are unsure of or that may have "
    "changed, use the available lookup tools — rather than guessing. If no tool is needed, answer "
    "directly."
)


@dataclass(frozen=True)
class TurnEvent:
    """One step of a turn: a reasoning/answer delta, a tool call/result, a plan/critique step, the
    final (``text`` carries the full answer), or an ``approval_request`` (durable human gate)."""

    kind: Literal[
        "reasoning",
        "answer",
        "tool",
        "final",
        "plan",
        "critique",
        "verification",
        "approval_request",
        "draft",
    ]
    text: str = ""
    phase: str = ""  # "call" | "result" for tool events
    tool: str | None = None
    args: Mapping[str, Any] | None = None
    ok: bool | None = None
    output: Mapping[str, Any] | None = None
    error: str | None = None
    usage: Mapping[str, int] | None = None
    verdict: str | None = None  # verification outcome (pass/needs_revision/fail) — M8.2
    attempt: int | None = None  # which researcher pass produced a `draft` (#393)


async def run_turn(
    *,
    generation: GenerationRequest,
    provider: ModelProvider,
    use_tools: bool,
    approve_tools: bool,
    tools: Sequence[Any],
    grants: Sequence[Any],
    gateway: Any,
    max_iterations: int,
    graph_enabled: bool = False,
    agent_prompts: Mapping[str, str] | None = None,
    accuracy_mode: str = "standard",
    context: AgentContext | None = None,
    checkpointer: Any | None = None,
    thread_id: str | None = None,
    resume: Any | None = None,
) -> AsyncIterator[TurnEvent]:
    """Drive one turn, yielding ordered TurnEvents (ending with a single ``final``, or an
    ``approval_request`` when the durable human gate suspends the run).

    With ``graph_enabled`` (M8, ADR-0012) the tool path runs through the typed graph, otherwise the
    single-agent loop (``run_agent``). A ``checkpointer`` (+ ``thread_id``) enables the durable
    human gate; ``resume`` continues a previously suspended run.
    """
    if use_tools:
        agent_events = (
            run_graph(
                messages=generation.messages,
                provider=provider,
                model=generation.model,
                gateway=gateway,
                tools=tools,
                grants=grants,
                approved=approve_tools,
                think=generation.think,
                max_iterations=max_iterations,
                context=context,
                checkpointer=checkpointer,
                thread_id=thread_id,
                resume=resume,
                prompts=agent_prompts,
                accuracy_mode=accuracy_mode,
            )
            if graph_enabled
            else run_agent(
                # Prepend the tool-use nudge so the single-agent model actually calls tools (#318).
                messages=[
                    ChatMessage(Role.SYSTEM, _SINGLE_AGENT_TOOL_PROMPT),
                    *generation.messages,
                ],
                provider=provider,
                model=generation.model,
                gateway=gateway,
                tools=tools,
                grants=grants,
                approved=approve_tools,
                think=generation.think,
                max_iterations=max_iterations,
            )
        )
        async for ev in agent_events:
            if ev.type == "reasoning":
                yield TurnEvent("reasoning", text=ev.thinking or "")
            elif ev.type == "answer":
                yield TurnEvent("answer", text=ev.answer or "")
            elif ev.type == "plan":
                yield TurnEvent("plan", text=ev.text or "")
            elif ev.type == "critique":
                yield TurnEvent("critique", text=ev.text or "")
            elif ev.type == "verification":
                yield TurnEvent("verification", text=ev.text or "", verdict=ev.verdict)
            elif ev.type == "draft":
                # The researcher's draft answer -> reasoning pane, not the output bubble (#393).
                yield TurnEvent("draft", text=ev.answer or "", attempt=ev.attempt)
            elif ev.type == "approval_request":
                yield TurnEvent("approval_request", output=ev.output or {})
            elif ev.type == "final":
                # text carries the full answer so a resumed stream (no deltas) can re-deliver it.
                yield TurnEvent("final", text=ev.answer or "", usage=ev.usage or {})
            else:  # tool_call | tool_result
                yield TurnEvent(
                    "tool",
                    phase="call" if ev.type == "tool_call" else "result",
                    tool=ev.tool,
                    args=ev.args,
                    ok=ev.ok,
                    output=ev.output,
                    error=ev.error,
                )
        return
    usage: Mapping[str, int] = {}
    async for chunk in provider.stream(generation):
        if chunk.thinking:
            yield TurnEvent("reasoning", text=chunk.thinking)
        if chunk.delta:
            yield TurnEvent("answer", text=chunk.delta)
        if chunk.usage:
            usage = dict(chunk.usage)
    yield TurnEvent("final", usage=usage)
