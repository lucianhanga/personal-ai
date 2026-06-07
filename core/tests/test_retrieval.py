"""VectorRetriever — tested with fakes (no DB, no live model)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from personalai_contracts.ports import (
    EmbeddingResult,
    RetrievalQuery,
    Retriever,
    VectorRecord,
)
from personalai_contracts.testing import FakeModelProvider, InMemoryVectorRepository
from personalai_core import VectorRetriever


def test_retriever_returns_cited_items() -> None:
    async def _run() -> None:
        vectors = InMemoryVectorRepository()
        await vectors.upsert(
            [
                VectorRecord(
                    id="d1:0",
                    vector=[0.1] * 8,
                    metadata={
                        "text": "Lisbon is the capital of Portugal.",
                        "document_id": "d1",
                        "chunk_index": 0,
                        "name": "geo.txt",
                    },
                )
            ]
        )
        retriever = VectorRetriever(FakeModelProvider(), vectors, "m")
        assert isinstance(retriever, Retriever)
        items = await retriever.retrieve(RetrievalQuery(text="capital?", top_k=3))
        assert items
        assert items[0].citation.source_id == "d1"
        assert items[0].citation.locator == "chunk 0"
        assert "Lisbon" in items[0].content

    asyncio.run(_run())


def test_retriever_locator_none_without_chunk_index() -> None:
    async def _run() -> None:
        vectors = InMemoryVectorRepository()
        await vectors.upsert([VectorRecord(id="x", vector=[0.2] * 8, metadata={"text": "t"})])
        items = await VectorRetriever(FakeModelProvider(), vectors, "m").retrieve(
            RetrievalQuery(text="q", top_k=1)
        )
        assert items[0].citation.locator is None
        assert items[0].citation.source_id == ""

    asyncio.run(_run())


def test_retriever_empty_when_no_embedding() -> None:
    class _NoEmbed(FakeModelProvider):
        async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
            return EmbeddingResult(vectors=[], model=model, dimensions=0)

    async def _run() -> None:
        items = await VectorRetriever(_NoEmbed(), InMemoryVectorRepository(), "m").retrieve(
            RetrievalQuery(text="q", top_k=3)
        )
        assert items == []

    asyncio.run(_run())
