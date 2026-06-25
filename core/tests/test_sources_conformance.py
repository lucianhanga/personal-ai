"""Source conformances (#420): vector/memory wrap existing seams -> Evidence; graph is a no-op stub.

Confirms each concrete source returns provenance-tagged Evidence with the right source_kind, and the
deferred GraphSource returns nothing while still conforming to the seam.
"""

from __future__ import annotations

import asyncio

from personalai_contracts.ports import (
    SOURCE_KIND_GRAPH,
    SOURCE_KIND_MEMORY,
    SOURCE_KIND_VECTOR,
    Citation,
    Evidence,
    MemoryKind,
    RetrievalQuery,
    RetrievalSource,
    RetrievedItem,
)
from personalai_contracts.testing import FakeModelProvider, InMemoryMemoryStore
from personalai_core.sources import GraphSource, MemorySource, VectorSource


class _FakeRetriever:
    name = "vector"

    async def retrieve(self, query: RetrievalQuery):  # type: ignore[no-untyped-def]
        return [
            RetrievedItem(
                content="chunk text",
                score=0.9,
                citation=Citation(source_id="doc-1", locator="chunk 0"),
                metadata={"name": "doc-1", "text": "chunk text"},
            )
        ]


def test_vector_source_maps_to_evidence_with_vector_kind() -> None:
    src = VectorSource(_FakeRetriever(), top_k=5)
    assert isinstance(src, RetrievalSource)  # conforms to the seam

    async def _run() -> list[Evidence]:
        return list(await src.retrieve("q", 6000, None))

    ev = asyncio.run(_run())
    assert len(ev) == 1
    assert ev[0].source_kind == SOURCE_KIND_VECTOR
    assert ev[0].citation.source_id == "doc-1"
    assert ev[0].text == "chunk text"


def test_memory_source_maps_recall_to_evidence_with_memory_kind() -> None:
    store = InMemoryMemoryStore()
    provider = FakeModelProvider()

    async def _seed_and_run() -> list[Evidence]:
        emb = await provider.embed(["the user likes tea"], "m")
        await store.add(
            id="m1",
            kind=MemoryKind.PREFERENCE,
            text="the user likes tea",
            embedding=emb.vectors[0],
            confidence=0.9,
            source={},
        )
        src = MemorySource(embed_provider=provider, embed_model="m", store=store, top_k=5)
        assert isinstance(src, RetrievalSource)
        return list(await src.retrieve("what does the user like", 6000, None))

    ev = asyncio.run(_seed_and_run())
    assert ev and ev[0].source_kind == SOURCE_KIND_MEMORY
    assert ev[0].citation.source_id.startswith("memory:")


def test_vector_source_select_is_none_and_budget_bounds_output() -> None:
    # select() defers to the planner (None). A tiny budget stops after the first item (the source
    # honors its merge-allocated budget defensively).
    class _Many:
        name = "vector"

        async def retrieve(self, query: RetrievalQuery):  # type: ignore[no-untyped-def]
            return [
                RetrievedItem("x" * 400, 0.9 - i * 0.1, Citation(f"d{i}"), {"name": f"d{i}"})
                for i in range(3)
            ]

    src = VectorSource(_Many(), top_k=5)

    async def _run() -> tuple[float | None, int]:
        score = await src.select("q", None)
        ev = list(await src.retrieve("q", 50, None))  # ~100 tokens each; 50-token budget
        return score, len(ev)

    score, n = asyncio.run(_run())
    assert score is None
    assert n == 1  # budget bounded to the first item


def test_memory_source_select_is_none_and_budget_bounds_output() -> None:
    store = InMemoryMemoryStore()
    provider = FakeModelProvider()

    async def _run() -> tuple[float | None, int]:
        for i in range(3):
            emb = await provider.embed([f"fact {i} " + "y" * 400], "m")
            await store.add(
                id=f"m{i}",
                kind=MemoryKind.SEMANTIC,
                text=f"fact {i} " + "y" * 400,
                embedding=emb.vectors[0],
                confidence=0.9,
                source={},
            )
        src = MemorySource(embed_provider=provider, embed_model="m", store=store, top_k=5)
        score = await src.select("q", None)
        ev = list(await src.retrieve("fact", 50, None))
        return score, len(ev)

    score, n = asyncio.run(_run())
    assert score is None
    assert n == 1  # budget bounded


def test_graph_source_is_a_conforming_noop() -> None:
    src = GraphSource()
    assert isinstance(src, RetrievalSource)
    assert src.kind == SOURCE_KIND_GRAPH

    async def _run() -> tuple[float | None, list[Evidence]]:
        score = await src.select("q", None)
        ev = list(await src.retrieve("q", 6000, None))
        return score, ev

    score, ev = asyncio.run(_run())
    assert score == 0.0  # never applicable
    assert ev == []  # deferred: returns nothing
