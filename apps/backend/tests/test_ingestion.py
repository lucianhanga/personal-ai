"""Ingestion orchestration — tested with fakes (no DB, no live model)."""

from __future__ import annotations

import asyncio

from personalai_backend.ingestion import chunk_ids, ingest_file
from personalai_contracts.testing import FakeModelProvider, InMemoryVectorRepository


def test_ingest_chunks_embeds_and_stores() -> None:
    async def _run() -> None:
        vectors = InMemoryVectorRepository()
        result = await ingest_file(
            content=b"hello world. " * 100,
            filename="notes.txt",
            document_id="d1",
            embed_model="m",
            provider=FakeModelProvider(),
            vectors=vectors,
            chunk_size=100,
            chunk_overlap=10,
        )
        assert result.chunk_count > 0
        assert result.mime == "text/plain"
        stored = await vectors.query([0.0] * 8, top_k=1000)  # FakeModelProvider embeds 8-dim
        assert len(stored) == result.chunk_count
        assert all(m.id.startswith("d1:") for m in stored)
        assert all(m.metadata["document_id"] == "d1" for m in stored)
        assert all("text" in m.metadata for m in stored)

    asyncio.run(_run())


def test_ingest_empty_content_stores_nothing() -> None:
    async def _run() -> None:
        vectors = InMemoryVectorRepository()
        result = await ingest_file(
            content=b"   \n  ",
            filename="blank.txt",
            document_id="d2",
            embed_model="m",
            provider=FakeModelProvider(),
            vectors=vectors,
        )
        assert result.chunk_count == 0
        assert await vectors.query([0.0] * 8, top_k=10) == []

    asyncio.run(_run())


def test_chunk_ids() -> None:
    assert chunk_ids("doc", 3) == ["doc:0", "doc:1", "doc:2"]
    assert chunk_ids("doc", 0) == []
