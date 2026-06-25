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


def test_truncate_from_is_rls_scoped_and_cross_tenant_safe() -> None:
    """#441: truncate_from runs under RLS — A's truncate confines to A's tenant, and B cannot
    truncate A's conversation even with A's exact message id (RLS makes the rows invisible)."""

    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            a = (await tenants.create_tenant("A")).id
            b = (await tenants.create_tenant("B")).id
            id_a = f"a-{uuid.uuid4()}"

            # A creates a conversation with two turns through a bound connection.
            async with tdb.acquire(a) as conn:
                store = PgConversationStore(conn)
                await store.create(id=id_a, title="A")
                m1 = await store.add_message(conversation_id=id_a, role="user", content="q1")
                await store.add_message(conversation_id=id_a, role="assistant", content="a1")

            # B tries to truncate A's conversation from A's message id -> RLS makes A's rows
            # invisible, so nothing is deleted (the delete matches no row under B's role).
            async with tdb.acquire(b) as conn:
                deleted_by_b = await PgConversationStore(conn).truncate_from(
                    id_a, from_message_id=m1.id
                )
            assert deleted_by_b == []

            # A's turns are intact; A can truncate its own conversation.
            async with tdb.acquire(a) as conn:
                store = PgConversationStore(conn)
                assert len(await store.list_messages(id_a)) == 2
                deleted_by_a = await store.truncate_from(id_a, from_message_id=m1.id)
                assert deleted_by_a == [m1.id] or m1.id in deleted_by_a
                assert await store.list_messages(id_a) == []
        finally:
            await pool.close()

    asyncio.run(_run())
