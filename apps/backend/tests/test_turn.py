"""run_turn orchestration is testable with fakes, no FastAPI (A4/#227)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from personalai_backend.turn import TurnEvent, run_turn
from personalai_contracts.ports import (
    ChatMessage,
    GenerationChunk,
    GenerationRequest,
    Role,
)
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


class _RecordingProvider(FakeModelProvider):
    """Captures the system prompts of the first model call so we can assert what was injected."""

    def __init__(self) -> None:
        super().__init__(name="rec")
        self.system_prompts: list[str] = []

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        if not self.system_prompts:
            self.system_prompts = [m.content for m in request.messages if m.role == Role.SYSTEM]
        async for chunk in super().stream(request):
            yield chunk


def _run_with(provider: _RecordingProvider, *, use_tools: bool) -> None:
    gen = GenerationRequest(messages=[ChatMessage(Role.USER, "what is 2+2?")], model="fake")

    async def _run() -> None:
        async for _ in run_turn(
            generation=gen,
            provider=provider,
            use_tools=use_tools,
            approve_tools=False,
            tools=[],
            grants=[],
            gateway=None,
            max_iterations=2,
        ):
            pass

    asyncio.run(_run())


def test_single_agent_with_tools_gets_a_tool_use_nudge() -> None:
    # use_tools=True, graph disabled -> the single-agent loop gets the tool-use instruction (#318).
    provider = _RecordingProvider()
    _run_with(provider, use_tools=True)
    assert any("tools available" in p.lower() for p in provider.system_prompts)


def test_plain_stream_has_no_tool_use_nudge() -> None:
    # use_tools=False -> plain provider stream; no tool nudge is injected.
    provider = _RecordingProvider()
    _run_with(provider, use_tools=False)
    assert not any("tools available" in p.lower() for p in provider.system_prompts)
