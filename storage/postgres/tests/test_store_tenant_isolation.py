"""P0.5: the Pg* stores isolate by tenant when given a TenantDb-bound connection (real Postgres)."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from personalai_storage_postgres import (
    PgConversationStore,
    PgTenantStore,
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


def test_conversation_store_isolates_via_tenant_db() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            a = (await tenants.create_tenant("A")).id
            b = (await tenants.create_tenant("B")).id
            id_a, id_b = f"a-{uuid.uuid4()}", f"b-{uuid.uuid4()}"

            # Each tenant creates a conversation through a bound connection; the INSERT stamps the
            # bound tenant via current_setting, satisfying RLS WITH CHECK.
            async with tdb.acquire(a) as conn:
                await PgConversationStore(conn).create(id=id_a, title="A")
            async with tdb.acquire(b) as conn:
                await PgConversationStore(conn).create(id=id_b, title="B")

            async with tdb.acquire(a) as conn:
                store = PgConversationStore(conn)
                ids = {c.id for c in await store.list()}
                assert id_a in ids and id_b not in ids  # A sees only its own
                assert await store.get(id_b) is None  # B's conversation is invisible to A
            async with tdb.acquire(b) as conn:
                assert (
                    await PgConversationStore(conn).get(id_b)
                ) is not None  # B still has its own
        finally:
            await pool.close()

    asyncio.run(_run())
