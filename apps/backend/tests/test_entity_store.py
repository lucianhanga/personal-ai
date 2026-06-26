"""KAG entity store (P3, #451): canonical upsert/dedup, mentions, edges, reconciler, isolation.

DB-gated (real Postgres). Pure relational checks -- no model/embeddings needed.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import asyncpg
import pytest

from personalai_backend.tenant_querier import TenantQuerier
from personalai_contracts.ports import SecurityContext
from personalai_core.security import current_security
from personalai_storage_postgres import PgEntityStore, apply_migrations, create_pool

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


pytestmark = pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")


def _run[T](coro_fn: Callable[[], Coroutine[Any, Any, T]]) -> T:
    return asyncio.run(coro_fn())


async def _new_tenant(pool: asyncpg.Pool) -> str:
    tid = str(uuid.uuid4())
    await pool.execute("INSERT INTO tenants (id, name) VALUES ($1, $2)", tid, f"t-{tid[:8]}")
    return tid


def _bind(tenant_id: str) -> None:
    current_security.set(SecurityContext(subject_id="test", tenant_id=tenant_id))


def test_canonical_upsert_dedups_and_normalizes() -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        _bind(await _new_tenant(pool))
        store = PgEntityStore(TenantQuerier(pool))
        # Same canonical (type, normalized_name) across docs -> one row, counts accumulate.
        id1 = await store.upsert_entity(type="org", name="Acme Corp", occurrences=2)
        id2 = await store.upsert_entity(type="org", name="  acme   corp ", occurrences=3)  # folds
        assert id1 == id2
        ents = await store.list_entities(type="org")
        assert len(ents) == 1
        assert ents[0].mention_count == 5  # 2 + 3 accumulated across the two upserts
        assert ents[0].normalized_name == "acme corp"  # generated key folds case + whitespace
        # Different type with the same name is a DISTINCT entity.
        await store.upsert_entity(type="person", name="Acme Corp", occurrences=1)
        assert len(await store.list_entities()) == 2
        await pool.close()

    _run(run)


def test_mentions_edges_and_search() -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        _bind(await _new_tenant(pool))
        store = PgEntityStore(TenantQuerier(pool))
        a = await store.upsert_entity(type="person", name="Ada Lovelace", occurrences=1)
        b = await store.upsert_entity(type="org", name="Analytical Engine", occurrences=1)
        await store.add_mention(entity_id=a, document_id="doc-1", occurrences=1)
        await store.add_mention(entity_id=b, document_id="doc-1", occurrences=1)
        await store.add_edge(src_entity_id=a, relation="worked_on", dst_entity_id=b)
        await store.add_edge(src_entity_id=a, relation="worked_on", dst_entity_id=a)  # self-loop

        assert set(await store.documents_for_entity(a)) == {"doc-1"}
        assert {e.id for e in await store.entities_for_document("doc-1")} == {a, b}
        assert await store.edges_for_entity(a) == [("worked_on", b)]
        # trigram-ish search over the normalized name.
        found = await store.list_entities(query="lovelace")
        assert [e.id for e in found] == [a]
        await pool.close()

    _run(run)


def test_purge_and_orphan_sweep_cascade() -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        _bind(await _new_tenant(pool))
        store = PgEntityStore(TenantQuerier(pool))
        a = await store.upsert_entity(type="person", name="Grace Hopper", occurrences=2)
        b = await store.upsert_entity(type="org", name="US Navy", occurrences=1)
        await store.add_mention(entity_id=a, document_id="d1", occurrences=2)
        await store.add_mention(entity_id=b, document_id="d1", occurrences=1)
        await store.add_edge(src_entity_id=a, relation="served_in", dst_entity_id=b)

        # Purge d1 -> mentions gone, counters decremented to zero.
        await store.purge_document_entities("d1")
        assert await store.documents_for_entity(a) == []
        # Sweep removes the now-unreferenced entities; their edge cascades.
        removed = await store.sweep_orphan_entities(grace_hours=0)
        assert removed == 2
        assert await store.list_entities() == []
        # Edge is gone (FK cascade) -- no error, just empty.
        assert await store.edges_for_entity(a) == []
        await pool.close()

    _run(run)


def test_tenant_isolation() -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        t1, t2 = await _new_tenant(pool), await _new_tenant(pool)
        _bind(t1)
        store = PgEntityStore(TenantQuerier(pool))
        await store.upsert_entity(type="person", name="Tenant One Only", occurrences=1)
        assert len(await store.list_entities()) == 1
        _bind(t2)
        assert await store.list_entities() == []  # RLS hides t1's entity from t2
        await pool.close()

    _run(run)
