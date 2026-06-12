"""A5: RLS isolates ALL five tenant tables (not just conversations) via the stores + TenantDb."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from personalai_contracts.ports import MemoryKind
from personalai_contracts.ports.storage import VectorRecord
from personalai_storage_postgres import (
    VECTOR_DIM,
    PgConversationStore,
    PgDocumentStore,
    PgMemoryStore,
    PgTenantStore,
    PgVectorRepository,
    TenantDb,
    apply_migrations,
    create_pool,
)

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


async def _counts(conn: object) -> dict[str, int]:
    return {
        "conversations": await conn.fetchval("SELECT count(*) FROM conversations"),  # type: ignore[attr-defined]
        "messages": await conn.fetchval("SELECT count(*) FROM messages"),  # type: ignore[attr-defined]
        "documents": await conn.fetchval("SELECT count(*) FROM documents"),  # type: ignore[attr-defined]
        "vectors": await conn.fetchval("SELECT count(*) FROM vectors"),  # type: ignore[attr-defined]
        "memories": await conn.fetchval("SELECT count(*) FROM memories"),  # type: ignore[attr-defined]
    }


def test_all_five_tenant_tables_are_isolated() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            a = (await tenants.create_tenant("A")).id
            b = (await tenants.create_tenant("B")).id
            cid = f"c-{uuid.uuid4()}"
            vec = [0.0] * VECTOR_DIM

            # Tenant A writes one row into each of the five tenant tables.
            async with tdb.acquire(a) as conn:
                await PgConversationStore(conn).create(id=cid, title="A secret")
                await PgConversationStore(conn).add_message(
                    conversation_id=cid, role="user", content="secret-A"
                )
                await PgDocumentStore(conn).add(
                    id=f"d-{uuid.uuid4()}",
                    name="a.txt",
                    mime="text/plain",
                    size_bytes=1,
                    chunk_count=1,
                )
                await PgVectorRepository(conn).upsert(
                    [VectorRecord(id=f"v-{uuid.uuid4()}", vector=vec, metadata={})]
                )
                await PgMemoryStore(conn).add(
                    id=f"m-{uuid.uuid4()}",
                    kind=MemoryKind.SEMANTIC,
                    text="mem-A",
                    embedding=vec,
                    confidence=1.0,
                    source={},
                )

            # Fresh tenant B (no rows of its own) sees ZERO across every table; A sees its own.
            async with tdb.acquire(b) as conn:
                assert all(n == 0 for n in (await _counts(conn)).values())
            async with tdb.acquire(a) as conn:
                assert all(n >= 1 for n in (await _counts(conn)).values())
        finally:
            await pool.close()

    asyncio.run(_run())
