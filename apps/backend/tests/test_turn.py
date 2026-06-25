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
    # Single-agent streams the answer to the output (no `draft`) — #393 is multi-agent only.
    assert all(e.kind != "draft" for e in events)


def _multi_events() -> list[TurnEvent]:
    gen = GenerationRequest(messages=[ChatMessage(Role.USER, "hi there")], model="fake")

    async def _run() -> list[TurnEvent]:
        return [
            ev
            async for ev in run_turn(
                generation=gen,
                provider=FakeModelProvider(name="fake"),
                use_tools=True,  # the graph path is taken only on the tool path
                approve_tools=False,
                tools=[],
                grants=[],
                gateway=None,
                max_iterations=8,
                graph_enabled=True,
            )
        ]

    return asyncio.run(_run())


def test_multi_agent_draft_to_trace_output_answer_from_finalize() -> None:
    # #393: in multi-agent mode the researcher's answer is a `draft` (reasoning pane); the OUTPUT
    # answer is emitted by finalize. So the stream carries a `draft`, ends in one `final`, and the
    # joined output `answer` equals the accepted draft.
    events = _multi_events()
    kinds = [e.kind for e in events]
    assert "draft" in kinds
    assert kinds[-1] == "final"
    drafts = [e for e in events if e.kind == "draft"]
    assert drafts and drafts[0].attempt == 1
    answer = "".join(e.text for e in events if e.kind == "answer")
    assert answer and answer == drafts[-1].text  # output answer == the accepted draft


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


class _StaticSource:
    """A multi-source RetrievalSource fake returning fixed Evidence (no LangChain, no DB)."""

    def __init__(self, name: str, kind: str, items: list) -> None:  # type: ignore[type-arg]
        self.name = name
        self.kind = kind
        self._items = items

    async def select(self, query, ctx):  # type: ignore[no-untyped-def]
        return None

    async def retrieve(self, query, budget, ctx):  # type: ignore[no-untyped-def]
        return self._items


def test_run_turn_multisource_forwards_unified_citations() -> None:
    # #420: with sources wired the graph emits a unified `citations` TurnEvent (source_kind aware)
    # before the researcher's draft, and the turn still ends in a single final.
    from personalai_contracts.ports import (
        SOURCE_KIND_MEMORY,
        SOURCE_KIND_VECTOR,
        Citation,
        Evidence,
    )

    gen = GenerationRequest(messages=[ChatMessage(Role.USER, "q")], model="fake")
    vector = _StaticSource(
        "vector",
        SOURCE_KIND_VECTOR,
        [
            Evidence(
                "doc fact", 0.9, Citation("doc-1", "chunk 0"), SOURCE_KIND_VECTOR, {"name": "d1"}
            )
        ],
    )
    memory = _StaticSource(
        "memory",
        SOURCE_KIND_MEMORY,
        [Evidence("user fact", 0.5, Citation("memory:1"), SOURCE_KIND_MEMORY, {"name": "Memory"})],
    )

    async def _run() -> list[TurnEvent]:
        return [
            ev
            async for ev in run_turn(
                generation=gen,
                provider=FakeModelProvider(name="fake"),
                use_tools=True,
                approve_tools=False,
                tools=[],
                grants=[],
                gateway=None,
                max_iterations=8,
                graph_enabled=True,
                sources=[vector, memory],
                retrieval_query="q",
            )
        ]

    events = asyncio.run(_run())
    kinds = [e.kind for e in events]
    assert "citations" in kinds
    assert kinds[-1] == "final"
    cite_ev = next(e for e in events if e.kind == "citations")
    cites = cite_ev.output["citations"]
    seen = {c["source_kind"] for c in cites}
    assert seen == {SOURCE_KIND_VECTOR, SOURCE_KIND_MEMORY}
    assert all("merged_from" in c for c in cites)


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
