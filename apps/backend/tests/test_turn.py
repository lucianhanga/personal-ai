"""run_turn orchestration is testable with fakes, no FastAPI (A4/#227)."""

from __future__ import annotations

import asyncio

from personalai_backend.turn import TurnEvent, run_turn
from personalai_contracts.ports import ChatMessage, GenerationRequest, Role
from personalai_contracts.testing import FakeModelProvider


def _events(use_tools: bool) -> list[TurnEvent]:
    gen = GenerationRequest(messages=[ChatMessage(Role.USER, "hi there")], model="fake")

    async def _run() -> list[TurnEvent]:
        return [
            ev
            async for ev in run_turn(
                generation=gen,
                provider=FakeModelProvider(name="fake"),
                use_tools=use_tools,
                approve_tools=False,
                tools=[],
                grants=[],
                gateway=None,
                max_iterations=8,
            )
        ]

    return asyncio.run(_run())


def test_run_turn_streams_answer_then_a_single_final() -> None:
    events = _events(use_tools=False)
    assert events[-1].kind == "final"  # always ends with exactly one final
    assert sum(1 for e in events if e.kind == "final") == 1
    answer = "".join(e.text for e in events if e.kind == "answer")
    assert "echo:" in answer  # FakeModelProvider echoes the prompt across answer events
