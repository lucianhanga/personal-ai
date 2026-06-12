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

from personalai_contracts.ports import GenerationRequest, ModelProvider
from personalai_core import run_agent


@dataclass(frozen=True)
class TurnEvent:
    """One step of a turn: a reasoning delta, an answer delta, a tool call/result, or the final."""

    kind: Literal["reasoning", "answer", "tool", "final"]
    text: str = ""
    phase: str = ""  # "call" | "result" for tool events
    tool: str | None = None
    args: Mapping[str, Any] | None = None
    ok: bool | None = None
    output: Mapping[str, Any] | None = None
    error: str | None = None
    usage: Mapping[str, int] | None = None


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
) -> AsyncIterator[TurnEvent]:
    """Drive one turn, yielding ordered TurnEvents (always ending with a single ``final``)."""
    if use_tools:
        async for ev in run_agent(
            messages=generation.messages,
            provider=provider,
            model=generation.model,
            gateway=gateway,
            tools=tools,
            grants=grants,
            approved=approve_tools,
            think=generation.think,
            max_iterations=max_iterations,
        ):
            if ev.type == "reasoning":
                yield TurnEvent("reasoning", text=ev.thinking or "")
            elif ev.type == "answer":
                yield TurnEvent("answer", text=ev.answer or "")
            elif ev.type == "final":
                yield TurnEvent("final", usage=ev.usage or {})
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
