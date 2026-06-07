"""Opt-in long-term memory pipeline test against REAL Postgres + Ollama.

Run only when asked (a DB + Ollama with the chat + mxbai-embed-large models must be available):

    PERSONALAI_MEMORY_IT=1 uv run pytest apps/backend/tests/test_memory_integration.py -q

CI exercises the same paths with a Postgres service + fake models (see test_conversations.py).
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from personalai_contracts.ports import ChatMessage, Role
from personalai_core import recall, remember
from personalai_provider_ollama import OllamaProvider
from personalai_storage_postgres import PgMemoryStore, apply_migrations, create_pool

pytestmark = pytest.mark.skipif(
    os.environ.get("PERSONALAI_MEMORY_IT") != "1",
    reason="set PERSONALAI_MEMORY_IT=1 (+ Postgres + Ollama) for the full memory pipeline",
)

DB_URL = os.environ.get(
    "PERSONALAI_DATABASE_URL", "postgresql://personalai@127.0.0.1:5432/personalai"
)
OLLAMA = os.environ.get("PERSONALAI_OLLAMA_HOST", "http://127.0.0.1:11434")
CHAT_MODEL = os.environ.get("PERSONALAI_MEMORY_IT_MODEL", "qwen3:8b")
EMBED_MODEL = os.environ.get("PERSONALAI_EMBED_MODEL", "mxbai-embed-large")


def test_remember_then_recall_across_turns() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        provider = OllamaProvider(base_url=OLLAMA)
        try:
            await apply_migrations(pool)
            await pool.execute("TRUNCATE memories")
            store = PgMemoryStore(pool)

            stored = await remember(
                messages=[
                    ChatMessage(Role.USER, "For the record, my favourite language is Rust."),
                    ChatMessage(Role.ASSISTANT, "Got it."),
                ],
                gen_provider=provider,
                gen_model=CHAT_MODEL,
                embed_provider=provider,
                embed_model=EMBED_MODEL,
                store=store,
                source={"conversation_id": str(uuid.uuid4())},
            )
            assert stored, "expected at least one memory to be extracted"

            hits = await recall(
                query="what is my favourite programming language?",
                embed_provider=provider,
                embed_model=EMBED_MODEL,
                store=store,
                top_k=5,
            )
            assert any("Rust" in h.text for h in hits)
        finally:
            await provider.aclose()
            await pool.close()

    asyncio.run(_run())
