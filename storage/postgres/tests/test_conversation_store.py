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


def test_truncate_from_deletes_target_and_after_only() -> None:
    """#441: truncate_from deletes id>=N (the targeted turn + everything after) and nothing earlier,
    bumps updated_at, returns the deleted ids, and is idempotent."""

    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            store = PgConversationStore(pool)
            cid = str(uuid.uuid4())
            await store.create(id=cid, title="Truncate")
            m1 = await store.add_message(conversation_id=cid, role="user", content="q1")
            a1 = await store.add_message(conversation_id=cid, role="assistant", content="a1")
            m2 = await store.add_message(conversation_id=cid, role="user", content="q2")
            a2 = await store.add_message(conversation_id=cid, role="assistant", content="a2")

            # Truncate from the second user turn: delete q2 + a2, keep q1 + a1.
            deleted = await store.truncate_from(cid, from_message_id=m2.id)
            assert sorted(deleted) == sorted([m2.id, a2.id])
            kept = await store.list_messages(cid)
            assert [m.id for m in kept] == [m1.id, a1.id]
            assert [m.content for m in kept] == ["q1", "a1"]

            # Idempotent: re-truncating from an already-deleted id removes nothing.
            assert await store.truncate_from(cid, from_message_id=m2.id) == []
            assert len(await store.list_messages(cid)) == 2

            # Truncating from the first turn empties it (but the conversation row remains).
            await store.truncate_from(cid, from_message_id=m1.id)
            assert await store.list_messages(cid) == []
            assert await store.get(cid) is not None
        finally:
            await pool.close()

    asyncio.run(_run())


def test_truncate_from_is_scoped_to_the_conversation() -> None:
    """#441: messages.id is GLOBAL, so the predicate keys on conversation_id AND id>=N. Truncating
    one conversation never touches another's rows, even ones with a higher global id."""

    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            store = PgConversationStore(pool)
            cid1, cid2 = str(uuid.uuid4()), str(uuid.uuid4())
            await store.create(id=cid1, title="One")
            await store.create(id=cid2, title="Two")
            m1 = await store.add_message(conversation_id=cid1, role="user", content="one")
            # cid2's rows are created AFTER, so they have HIGHER global ids. An id-only predicate
            # (id >= m1.id) would wrongly sweep them up; the conversation_id guard prevents that.
            b1 = await store.add_message(conversation_id=cid2, role="user", content="two-a")
            b2 = await store.add_message(conversation_id=cid2, role="assistant", content="two-b")
            assert b1.id > m1.id and b2.id > m1.id

            deleted = await store.truncate_from(cid1, from_message_id=m1.id)
            assert deleted == [m1.id]  # only cid1's own row, despite cid2 having higher ids
            assert await store.list_messages(cid1) == []
            # cid2 is entirely untouched.
            assert [m.id for m in await store.list_messages(cid2)] == [b1.id, b2.id]
        finally:
            await pool.close()

    asyncio.run(_run())
