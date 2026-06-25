"""Phase 0 PR1 (#420 / #423): the anti-bleed scope regression suite -- the HARD gate.

Against a REAL Postgres + pgvector (the generated `tsv` column and scope FKs only exist in the DB,
not in fakes). Skipped when no database is reachable (run `make db` locally; CI provides a service
container) -- same pattern as test_vector_repo.py / test_rls_all_tables.py.

Proves:
  * a vector/document written in conversation scope is NOT returned by a global query;
  * a global vector/document is NOT returned by a conversation-scoped query;
  * tenant isolation still holds with scope in play;
  * deleting a conversation cascades its scoped vectors/documents (FK ON DELETE CASCADE).
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
    PgDocumentStore,
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


def test_global_query_excludes_conversation_scoped_vectors() -> None:
    """A conversation-scoped vector must never bleed into a global (Settings) retrieval."""

    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            tid = (await tenants.create_tenant("scope-global")).id
            cid = f"c-{uuid.uuid4()}"
            global_id = f"v-global-{uuid.uuid4()}"
            conv_id = f"v-conv-{uuid.uuid4()}"

            async with tdb.acquire(tid) as conn:
                await PgConversationStore(conn).create(id=cid, title="attach")
                repo = PgVectorRepository(conn)
                # Identical embeddings: only the scope column differs, so any leak is a scope bug.
                await repo.upsert([VectorRecord(id=global_id, vector=_vec(1.0), metadata={})])
                await repo.upsert(
                    [VectorRecord(id=conv_id, vector=_vec(1.0), metadata={})],
                    scope=Scope(conversation_id=cid),
                )

                # Global query (default scope) sees only the global row.
                global_hits = {m.id for m in await repo.query(_vec(1.0), top_k=50)}
                assert global_id in global_hits
                assert conv_id not in global_hits

                # Conversation-scoped query sees only the conversation row, never the global one.
                conv_hits = {
                    m.id
                    for m in await repo.query(_vec(1.0), top_k=50, scope=Scope(conversation_id=cid))
                }
                assert conv_id in conv_hits
                assert global_id not in conv_hits
        finally:
            await pool.close()

    asyncio.run(_run())


def test_global_document_list_excludes_conversation_scoped_documents() -> None:
    """PgDocumentStore.list() (global default) must hide conversation-scoped documents."""

    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            tid = (await tenants.create_tenant("scope-docs")).id
            cid = f"c-{uuid.uuid4()}"
            gdoc = f"d-global-{uuid.uuid4()}"
            cdoc = f"d-conv-{uuid.uuid4()}"

            async with tdb.acquire(tid) as conn:
                await PgConversationStore(conn).create(id=cid, title="attach")
                docs = PgDocumentStore(conn)
                await docs.add(
                    id=gdoc, name="g.txt", mime="text/plain", size_bytes=1, chunk_count=1
                )
                await docs.add(
                    id=cdoc,
                    name="c.txt",
                    mime="text/plain",
                    size_bytes=1,
                    chunk_count=1,
                    scope=Scope(conversation_id=cid),
                )

                global_ids = {d.id for d in await docs.list()}
                assert gdoc in global_ids
                assert cdoc not in global_ids

                conv_ids = {d.id for d in await docs.list(scope=Scope(conversation_id=cid))}
                assert cdoc in conv_ids
                assert gdoc not in conv_ids
        finally:
            await pool.close()

    asyncio.run(_run())


def test_scope_does_not_break_tenant_isolation() -> None:
    """Scope is additive to RLS: tenant B never sees tenant A's rows, scoped or global."""

    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            a = (await tenants.create_tenant("scope-A")).id
            b = (await tenants.create_tenant("scope-B")).id
            cid = f"c-{uuid.uuid4()}"
            a_global = f"v-a-global-{uuid.uuid4()}"
            a_conv = f"v-a-conv-{uuid.uuid4()}"

            async with tdb.acquire(a) as conn:
                await PgConversationStore(conn).create(id=cid, title="A")
                repo = PgVectorRepository(conn)
                await repo.upsert([VectorRecord(id=a_global, vector=_vec(1.0), metadata={})])
                await repo.upsert(
                    [VectorRecord(id=a_conv, vector=_vec(1.0), metadata={})],
                    scope=Scope(conversation_id=cid),
                )

            # Tenant B: RLS yields nothing for either scope (it cannot see A's conversation).
            async with tdb.acquire(b) as conn:
                repo = PgVectorRepository(conn)
                assert await repo.query(_vec(1.0), top_k=50) == []
                assert await repo.query(_vec(1.0), top_k=50, scope=Scope(conversation_id=cid)) == []
        finally:
            await pool.close()

    asyncio.run(_run())


def test_deleting_conversation_cascades_scoped_vectors_and_documents() -> None:
    """The composite scope FK (ON DELETE CASCADE) GCs conversation rows; global rows persist."""

    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            tid = (await tenants.create_tenant("scope-cascade")).id
            cid = f"c-{uuid.uuid4()}"
            gvec = f"v-global-{uuid.uuid4()}"
            cvec = f"v-conv-{uuid.uuid4()}"
            cdoc = f"d-conv-{uuid.uuid4()}"

            async with tdb.acquire(tid) as conn:
                convs = PgConversationStore(conn)
                await convs.create(id=cid, title="attach")
                repo = PgVectorRepository(conn)
                await repo.upsert([VectorRecord(id=gvec, vector=_vec(1.0), metadata={})])
                await repo.upsert(
                    [VectorRecord(id=cvec, vector=_vec(1.0), metadata={})],
                    scope=Scope(conversation_id=cid),
                )
                await PgDocumentStore(conn).add(
                    id=cdoc,
                    name="c.txt",
                    mime="text/plain",
                    size_bytes=1,
                    chunk_count=1,
                    scope=Scope(conversation_id=cid),
                )

                await convs.delete(cid)

                remaining = {m.id for m in await repo.query(_vec(1.0), top_k=50)}
                assert gvec in remaining  # global row survives the conversation delete
                assert cvec not in remaining  # scoped vector cascaded away
                conv_docs = {d.id for d in await PgDocumentStore(conn).list()}
                assert cdoc not in conv_docs  # scoped document cascaded away
        finally:
            await pool.close()

    asyncio.run(_run())
