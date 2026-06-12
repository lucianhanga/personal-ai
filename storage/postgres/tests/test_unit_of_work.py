"""A3: TenantDb.acquire is a tenant-bound unit-of-work (ops commit/roll back together)."""

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


def test_unit_of_work_commits_multiple_ops_atomically() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tdb = TenantDb(pool)
            a = (await PgTenantStore(pool).create_tenant("A")).id
            cid = f"c-{uuid.uuid4()}"
            # One transaction: conversation + a message commit together.
            async with tdb.acquire(a) as conn:
                store = PgConversationStore(conn)
                await store.create(id=cid, title="t")
                await store.add_message(conversation_id=cid, role="user", content="hi")
            async with tdb.acquire(a) as conn:
                store = PgConversationStore(conn)
                assert (await store.get(cid)) is not None
                assert len(await store.list_messages(cid)) == 1
        finally:
            await pool.close()

    asyncio.run(_run())


def test_unit_of_work_rolls_back_on_error() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tdb = TenantDb(pool)
            a = (await PgTenantStore(pool).create_tenant("A")).id
            cid = f"c-{uuid.uuid4()}"
            with pytest.raises(RuntimeError):
                async with tdb.acquire(a) as conn:
                    await PgConversationStore(conn).create(id=cid, title="t")
                    raise RuntimeError("boom")  # must roll back the create
            async with tdb.acquire(a) as conn:
                assert (await PgConversationStore(conn).get(cid)) is None  # rolled back
        finally:
            await pool.close()

    asyncio.run(_run())


def test_add_message_bumps_conversation_updated_at_atomically() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tdb = TenantDb(pool)
            a = (await PgTenantStore(pool).create_tenant("A")).id
            cid = f"c-{uuid.uuid4()}"
            async with tdb.acquire(a) as conn:
                store = PgConversationStore(conn)
                conv = await store.create(id=cid, title="t")
                await asyncio.sleep(0.01)
                await store.add_message(conversation_id=cid, role="user", content="hi")
                after = await store.get(cid)
            assert after is not None and after.updated_at >= conv.updated_at
        finally:
            await pool.close()

    asyncio.run(_run())
