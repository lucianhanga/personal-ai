"""Phase 0 PR2 (#420 / #434): the hybrid (dense + lexical RRF, k=60) retrieval suite.

Against a REAL Postgres + pgvector (the `tsv` GIN, the RRF SQL, and the scope predicate only exist
in the DB, not in fakes). Skipped when no database is reachable (run `make db` locally; CI provides
a service container) -- same pattern as test_vector_repo.py / test_scope_isolation.py.

Proves:
  * a lexical-exact match the DENSE arm alone would rank lower surfaces via RRF (the core win);
  * hybrid retrieval stays GLOBAL by default -- conversation-scoped rows never bleed in (PR2 keeps
    retrieval global; conversation/project scope is PR4);
  * the returned VectorMatch shape (score + metadata) is preserved so citations survive.
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


def test_hybrid_surfaces_lexical_exact_match_dense_would_miss() -> None:
    """The RRF win: a chunk whose text exactly matches the query term but whose embedding is far
    from the query vector must surface above a chunk the dense arm alone would rank first."""

    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            tid = (await tenants.create_tenant("hybrid-lexical")).id
            # The unique term that only the lexical arm can match exactly.
            term = f"zylophon{uuid.uuid4().hex[:8]}"
            lexical_id = f"v-lexical-{uuid.uuid4()}"
            dense_id = f"v-dense-{uuid.uuid4()}"

            async with tdb.acquire(tid) as conn:
                repo = PgVectorRepository(conn)
                # The lexical hit: text contains the exact term, but its embedding is ORTHOGONAL to
                # the query vector (dense distance is maximal -> the dense arm ranks it last).
                await repo.upsert(
                    [
                        VectorRecord(
                            id=lexical_id,
                            vector=_vec(0.0, 1.0),
                            metadata={"text": f"the {term} report", "document_id": "d1"},
                        )
                    ]
                )
                # The dense favourite: embedding aligned with the query vector, but its text does
                # NOT contain the term (the lexical arm cannot match it at all).
                await repo.upsert(
                    [
                        VectorRecord(
                            id=dense_id,
                            vector=_vec(1.0, 0.0),
                            metadata={"text": "an unrelated summary", "document_id": "d2"},
                        )
                    ]
                )

                # Query vector aligns with the dense favourite; query TEXT is the exact term.
                results = await repo.hybrid_query(_vec(1.0, 0.0), term, top_k=10)
                ids = [m.id for m in results]
                assert lexical_id in ids, "lexical-exact match must be retrieved at all"
                assert dense_id in ids
                # RRF: the lexical arm ranks lexical_id #1 (rnk 1 -> 1/61) while the dense arm ranks
                # it last; the dense favourite is dense-rnk 1 but absent from the lexical arm. The
                # lexical hit's combined RRF score must lift it above the dense-only favourite.
                assert ids.index(lexical_id) < ids.index(dense_id), (
                    "RRF must surface the lexical-exact hit above the dense-only favourite"
                )

                # The VectorMatch shape is preserved (score + metadata -> citations survive).
                lexical_match = next(m for m in results if m.id == lexical_id)
                assert lexical_match.score > 0
                assert lexical_match.metadata["document_id"] == "d1"
                assert lexical_match.metadata["text"] == f"the {term} report"
        finally:
            await pool.close()

    asyncio.run(_run())


def test_hybrid_query_stays_global_excludes_conversation_scope() -> None:
    """Hybrid retrieval keeps the anti-bleed guarantee: a conversation-scoped chunk that lexically
    matches must NOT appear in a global hybrid query (PR2 retrieval is global; scope is PR4)."""

    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            tid = (await tenants.create_tenant("hybrid-scope")).id
            cid = f"c-{uuid.uuid4()}"
            term = f"quasar{uuid.uuid4().hex[:8]}"
            global_id = f"v-global-{uuid.uuid4()}"
            conv_id = f"v-conv-{uuid.uuid4()}"

            async with tdb.acquire(tid) as conn:
                await PgConversationStore(conn).create(id=cid, title="attach")
                repo = PgVectorRepository(conn)
                # Both rows contain the exact term and the SAME embedding: only scope differs, so
                # any leak is a scope bug -- not a ranking artefact.
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
                            id=conv_id,
                            vector=_vec(1.0),
                            metadata={"text": f"conv {term}", "document_id": "dc"},
                        )
                    ],
                    scope=Scope(conversation_id=cid),
                )

                # Global hybrid query (default scope) sees only the global row.
                global_hits = {m.id for m in await repo.hybrid_query(_vec(1.0), term, top_k=50)}
                assert global_id in global_hits
                assert conv_id not in global_hits

                # Conversation-scoped hybrid query sees only the conversation row.
                conv_hits = {
                    m.id
                    for m in await repo.hybrid_query(
                        _vec(1.0), term, top_k=50, scope=Scope(conversation_id=cid)
                    )
                }
                assert conv_id in conv_hits
                assert global_id not in conv_hits
        finally:
            await pool.close()

    asyncio.run(_run())


def test_hybrid_query_with_no_lexical_match_falls_back_to_dense() -> None:
    """When the query text matches no chunk lexically, the lexical arm is empty and RRF degrades to
    dense-only ranking (a recall-preserving, not breaking, behaviour)."""

    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            tid = (await tenants.create_tenant("hybrid-dense-only")).id
            near_id = f"v-near-{uuid.uuid4()}"
            far_id = f"v-far-{uuid.uuid4()}"

            async with tdb.acquire(tid) as conn:
                repo = PgVectorRepository(conn)
                await repo.upsert(
                    [VectorRecord(id=near_id, vector=_vec(1.0, 0.0), metadata={"text": "alpha"})]
                )
                await repo.upsert(
                    [VectorRecord(id=far_id, vector=_vec(0.0, 1.0), metadata={"text": "beta"})]
                )

                # A query term that exists in no chunk -> lexical arm empty -> dense order holds.
                results = await repo.hybrid_query(_vec(1.0, 0.0), "nonexistentterm12345", top_k=10)
                ids = [m.id for m in results]
                assert ids[0] == near_id
        finally:
            await pool.close()

    asyncio.run(_run())
