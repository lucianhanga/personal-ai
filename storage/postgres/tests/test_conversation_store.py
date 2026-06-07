"""PgConversationStore against a REAL Postgres (skipped when no DB)."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from personalai_storage_postgres import PgConversationStore, apply_migrations, create_pool

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


def test_conversation_crud_and_messages() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            store = PgConversationStore(pool)
            cid = str(uuid.uuid4())
            conv = await store.create(id=cid, title="Trip plan")
            assert conv.title == "Trip plan"

            await store.add_message(conversation_id=cid, role="user", content="hi")
            await store.add_message(conversation_id=cid, role="assistant", content="hello")
            msgs = await store.list_messages(cid)
            assert [m.role for m in msgs] == ["user", "assistant"]
            assert [m.content for m in msgs] == ["hi", "hello"]

            assert any(c.id == cid for c in await store.list())
            fetched = await store.get(cid)
            assert fetched is not None and fetched.title == "Trip plan"

            await store.delete(cid)
            assert await store.get(cid) is None
            assert await store.list_messages(cid) == []  # cascade-deleted with the conversation

        finally:
            await pool.close()

    asyncio.run(_run())
