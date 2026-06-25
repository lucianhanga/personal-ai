"""Phase 0 PR4 (#420 / #436): the global+conversation UNION retrieval + anti-bleed suite.

Against a REAL Postgres + pgvector -- the union scope predicate, the RRF SQL, and the FK cascade
only exist in the DB, not in fakes. Skipped when no database is reachable (run `make db` locally; CI
provides a service container) -- same pattern as test_hybrid_query.py / test_scope_isolation.py.

Proves the tier-2 invariants:
  * a UNION retrieval (``union_conversation_id=A``) returns BOTH the global corpus AND conversation
    A's ephemeral attachments (so the attached doc and Settings -> Documents are both searchable);
  * ANTI-BLEED (the critical invariant): conversation B's doc NEVER surfaces in A's union, and a
    no-conversation (global) request sees neither A's nor B's conversation rows;
  * deleting a conversation cascades its vectors away (PR1 FK), so GC needs no new code.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from personalai_contracts.ports.storage import Scope, VectorRecord
from personalai_storage_postgres import (
    VECTOR_DIM,
    PgConversationStore,
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


def _vec(*lead: float) -> list[float]:
    """A VECTOR_DIM-long vector with the given leading values, zero-padded."""
    return list(lead) + [0.0] * (VECTOR_DIM - len(lead))


def test_union_returns_global_and_this_conversation_but_not_others() -> None:
    """The PR4 contract: a union retrieval for conversation A returns the global corpus AND A's
    ephemeral attachment, but NOT conversation B's attachment (anti-bleed). All rows share the exact
    term + embedding, so any cross-conversation hit is a scope bug, not a ranking artefact."""

    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            tid = (await tenants.create_tenant("union-retrieval")).id
            conv_a = f"a-{uuid.uuid4()}"
            conv_b = f"b-{uuid.uuid4()}"
            term = f"wexford{uuid.uuid4().hex[:8]}"
            global_id = f"v-global-{uuid.uuid4()}"
            a_id = f"v-a-{uuid.uuid4()}"
            b_id = f"v-b-{uuid.uuid4()}"

            async with tdb.acquire(tid) as conn:
                convs = PgConversationStore(conn)
                await convs.create(id=conv_a, title="chat A")
                await convs.create(id=conv_b, title="chat B")
                repo = PgVectorRepository(conn)
                # One global row, one row scoped to A, one row scoped to B -- identical text/vector.
                await repo.upsert(
                    [
                        VectorRecord(
                            id=global_id,
                            vector=_vec(1.0),
                            metadata={"text": f"global {term}", "document_id": "dg"},
                        )
                    ]
                )
                await repo.upsert(
                    [
                        VectorRecord(
                            id=a_id,
                            vector=_vec(1.0),
                            metadata={"text": f"chatA {term}", "document_id": "da"},
                        )
                    ],
                    scope=Scope(conversation_id=conv_a),
                )
                await repo.upsert(
                    [
                        VectorRecord(
                            id=b_id,
                            vector=_vec(1.0),
                            metadata={"text": f"chatB {term}", "document_id": "db"},
                        )
                    ],
                    scope=Scope(conversation_id=conv_b),
                )

                # UNION for A: global + A's doc, never B's doc (the anti-bleed HARD gate).
                a_union = {
                    m.id
                    for m in await repo.hybrid_query(
                        _vec(1.0), term, top_k=50, union_conversation_id=conv_a
                    )
                }
                assert global_id in a_union, "global corpus must stay searchable in a union"
                assert a_id in a_union, "this conversation's attachment must be searchable"
                assert b_id not in a_union, "ANTI-BLEED: conversation B's doc must not surface in A"

                # Symmetric check for B: never sees A's doc.
                b_union = {
                    m.id
                    for m in await repo.hybrid_query(
                        _vec(1.0), term, top_k=50, union_conversation_id=conv_b
                    )
                }
                assert global_id in b_union
                assert b_id in b_union
                assert a_id not in b_union, "ANTI-BLEED: conversation B must NOT see A's doc"

                # No-conversation request (global default) sees neither conversation's rows.
                global_only = {m.id for m in await repo.hybrid_query(_vec(1.0), term, top_k=50)}
                assert global_id in global_only
                assert a_id not in global_only
                assert b_id not in global_only

                # The same invariant holds for the dense-only query() path used elsewhere.
                a_dense = {
                    m.id
                    for m in await repo.query(_vec(1.0), top_k=50, union_conversation_id=conv_a)
                }
                assert {global_id, a_id} <= a_dense
                assert b_id not in a_dense
        finally:
            await pool.close()

    asyncio.run(_run())


def test_conversation_delete_cascades_attachment_vectors() -> None:
    """GC by the PR1 FK cascade (#436 relies on it; no new GC code): deleting the conversation
    removes its scoped vectors, so a later union for that (now-gone) id finds none of them."""

    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            tid = (await tenants.create_tenant("union-gc")).id
            cid = f"c-{uuid.uuid4()}"
            term = f"ephemeral{uuid.uuid4().hex[:8]}"
            conv_vec_id = f"v-conv-{uuid.uuid4()}"

            async with tdb.acquire(tid) as conn:
                convs = PgConversationStore(conn)
                await convs.create(id=cid, title="to delete")
                repo = PgVectorRepository(conn)
                await repo.upsert(
                    [
                        VectorRecord(
                            id=conv_vec_id,
                            vector=_vec(1.0),
                            metadata={"text": f"conv {term}", "document_id": "dx"},
                        )
                    ],
                    scope=Scope(conversation_id=cid),
                )
                before = {
                    m.id
                    for m in await repo.hybrid_query(
                        _vec(1.0), term, top_k=50, union_conversation_id=cid
                    )
                }
                assert conv_vec_id in before

                # Delete the conversation -> the FK ON DELETE CASCADE drops its vectors.
                await convs.delete(cid)

                after = {
                    m.id
                    for m in await repo.hybrid_query(
                        _vec(1.0), term, top_k=50, union_conversation_id=cid
                    )
                }
                assert conv_vec_id not in after, "conversation delete must cascade its vectors away"
        finally:
            await pool.close()

    asyncio.run(_run())
