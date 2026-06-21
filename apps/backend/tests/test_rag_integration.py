"""Opt-in full RAG pipeline test against REAL Postgres + Ollama embeddings.

Skipped unless PERSONALAI_RAG_IT=1 (and a DB + Ollama with qwen3-embedding:0.6b are available):

    PERSONALAI_RAG_IT=1 uv run pytest apps/backend/tests/test_rag_integration.py -q

CI exercises the same code paths with a Postgres service + fake embeddings (see test_files.py).
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from personalai_backend.ingestion import ingest_file
from personalai_contracts.ports import RetrievalQuery
from personalai_core import VectorRetriever
from personalai_provider_ollama import OllamaProvider
from personalai_storage_postgres import PgVectorRepository, apply_migrations, create_pool

pytestmark = pytest.mark.skipif(
    os.environ.get("PERSONALAI_RAG_IT") != "1",
    reason="set PERSONALAI_RAG_IT=1 (+ Postgres + Ollama qwen3-embedding:0.6b) for the pipeline",
)

DB_URL = os.environ.get(
    "PERSONALAI_DATABASE_URL", "postgresql://personalai@127.0.0.1:5432/personalai"
)
OLLAMA = os.environ.get("PERSONALAI_OLLAMA_HOST", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("PERSONALAI_EMBED_MODEL", "qwen3-embedding:0.6b")


def test_full_rag_pipeline_ingest_then_retrieve() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        provider = OllamaProvider(base_url=OLLAMA)
        try:
            await apply_migrations(pool)
            await pool.execute("TRUNCATE vectors")
            vectors = PgVectorRepository(pool)

            document_id = str(uuid.uuid4())
            result = await ingest_file(
                content=b"The project mascot is a teal octopus named Wexford.",
                filename="fact.txt",
                document_id=document_id,
                embed_model=EMBED_MODEL,
                provider=provider,
                vectors=vectors,
            )
            assert result.chunk_count > 0

            retriever = VectorRetriever(provider, vectors, EMBED_MODEL)
            items = await retriever.retrieve(
                RetrievalQuery(text="What is the project mascot?", top_k=3)
            )
            assert any("Wexford" in item.content for item in items)
            assert items[0].citation.source_id == document_id
        finally:
            await provider.aclose()
            await pool.close()

    asyncio.run(_run())
