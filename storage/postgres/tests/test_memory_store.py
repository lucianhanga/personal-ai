"""PgMemoryStore against a REAL Postgres + pgvector (skipped when no DB)."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from personalai_contracts.ports import MemoryKind
from personalai_storage_postgres import VECTOR_DIM, PgMemoryStore, apply_migrations, create_pool

DB_URL = os.environ.get(
    "PERSONALAI_DATABASE_URL", "postgresql://personalai@127.0.0.1:5432/personalai"
)


def _db_available() -> bool:
    async def _check() -> bool:
        try:
            pool = await create_pool(DB_URL)
        except Exception:
            return False
        await pool.close()
        return True

    return asyncio.run(_check())


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="Postgres not reachable (run `make db`)"
)


def _vec(*lead: float) -> list[float]:
    return list(lead) + [0.0] * (VECTOR_DIM - len(lead))


def test_memory_add_search_update_delete_clear() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            await pool.execute("TRUNCATE memories")
            store = PgMemoryStore(pool)

            mid = str(uuid.uuid4())
            item = await store.add(
                id=mid,
                kind=MemoryKind.SEMANTIC,
                text="Lucian works at Hyperneers GmbH",
                embedding=_vec(1.0, 0.0),
                confidence=0.95,
                source={"conversation_id": "c1"},
            )
            assert item.kind is MemoryKind.SEMANTIC
            assert item.source["conversation_id"] == "c1"

            await store.add(
                id=str(uuid.uuid4()),
                kind=MemoryKind.PREFERENCE,
                text="prefers concise answers",
                embedding=_vec(0.0, 1.0),
                confidence=0.8,
                source={},
            )

            hits = await store.search(_vec(1.0, 0.0), top_k=2)
            assert hits[0].text == "Lucian works at Hyperneers GmbH"
            assert hits[0].score is not None and hits[0].score >= hits[1].score  # type: ignore[operator]

            assert len(await store.list()) == 2
            assert (await store.get(mid)) is not None

            updated = await store.update_text(mid, "Lucian works at Hyperneers")
            assert updated is not None and updated.text == "Lucian works at Hyperneers"
            assert await store.update_text("missing", "x") is None

            await store.delete(mid)
            assert await store.get(mid) is None

            await store.clear()
            assert await store.list() == []
        finally:
            await pool.close()

    asyncio.run(_run())
