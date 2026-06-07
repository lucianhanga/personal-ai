"""Long-term memory extraction + remember orchestration (fakes, no DB/live model)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from personalai_contracts.ports import (
    ChatMessage,
    EmbeddingResult,
    GenerationRequest,
    GenerationResult,
    MemoryKind,
    Role,
)
from personalai_contracts.testing import FakeModelProvider, InMemoryMemoryStore
from personalai_core import extract_facts, remember

TWO_FACTS = (
    '{"facts":['
    '{"kind":"semantic","text":"Lucian works at Hyperneers GmbH","confidence":0.95},'
    '{"kind":"preference","text":"prefers concise answers","confidence":0.8}]}'
)


class _FactProvider(FakeModelProvider):
    """generate() returns fixed extraction JSON; embed() gives one-hot vectors per unique text."""

    def __init__(self, facts_json: str, dim: int = 16) -> None:
        super().__init__(name="facts")
        self._facts_json = facts_json
        self._dim = dim
        self._idx: dict[str, int] = {}

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(text=self._facts_json, model=request.model)

    async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
        vectors: list[list[float]] = []
        for t in texts:
            self._idx.setdefault(t, len(self._idx))
            vec = [0.0] * self._dim
            vec[self._idx[t]] = 1.0
            vectors.append(vec)
        return EmbeddingResult(vectors=vectors, model=model, dimensions=self._dim)


def _msgs() -> list[ChatMessage]:
    return [ChatMessage(Role.USER, "where do I work?")]


def test_extract_facts_parses_filters_and_fails_closed() -> None:
    async def _run() -> None:
        facts = await extract_facts(_FactProvider(TWO_FACTS), "m", _msgs())
        assert {f.text for f in facts} == {
            "Lucian works at Hyperneers GmbH",
            "prefers concise answers",
        }
        low = '{"facts":[{"kind":"semantic","text":"meh","confidence":0.1}]}'
        assert await extract_facts(_FactProvider(low), "m", _msgs()) == []
        assert await extract_facts(_FactProvider("not json"), "m", _msgs()) == []

    asyncio.run(_run())


def test_remember_stores_then_dedups() -> None:
    async def _run() -> None:
        store = InMemoryMemoryStore()
        provider = _FactProvider(TWO_FACTS)
        stored = await remember(
            messages=_msgs(),
            gen_provider=provider,
            gen_model="m",
            embed_provider=provider,
            embed_model="m",
            store=store,
            source={"conversation_id": "c1"},
        )
        assert len(stored) == 2
        assert {s.kind for s in stored} == {MemoryKind.SEMANTIC, MemoryKind.PREFERENCE}
        assert all(s.source["conversation_id"] == "c1" for s in stored)

        # Re-running with the same facts stores nothing new (near-identical -> deduped).
        again = await remember(
            messages=_msgs(),
            gen_provider=provider,
            gen_model="m",
            embed_provider=provider,
            embed_model="m",
            store=store,
            source={"conversation_id": "c2"},
        )
        assert again == []
        assert len(await store.list()) == 2

    asyncio.run(_run())


def test_remember_skips_when_no_embedding() -> None:
    class _NoEmbed(_FactProvider):
        async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
            return EmbeddingResult(vectors=[], model=model, dimensions=0)

    async def _run() -> None:
        store = InMemoryMemoryStore()
        provider = _NoEmbed(TWO_FACTS)
        stored = await remember(
            messages=_msgs(),
            gen_provider=provider,
            gen_model="m",
            embed_provider=provider,
            embed_model="m",
            store=store,
            source={},
        )
        assert stored == []

    asyncio.run(_run())
