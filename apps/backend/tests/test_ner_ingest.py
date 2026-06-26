"""NER -> KAG ingest wiring (Documents v2 P3, #451): index_document_entities end to end.

DB-gated. The LLM extractor is STUBBED (monkeypatched) so the test is deterministic and needs no
model -- it exercises the real store path: extract -> upsert (canonical dedup) -> mention -> edge,
idempotent re-extraction, and document purge cascading the entities.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import asyncpg
import pytest

from personalai_backend import entity_indexing
from personalai_backend.entity_indexing import index_document_entities
from personalai_backend.tenant_querier import TenantQuerier
from personalai_contracts.ports import SecurityContext
from personalai_contracts.testing import FakeModelProvider
from personalai_core.entity_extraction import (
    ExtractedEntities,
    ExtractedEntity,
    ExtractedRelation,
)
from personalai_core.security import current_security
from personalai_storage_postgres import (
    PgEntityStore,
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


pytestmark = pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")

# What the (stubbed) extractor "finds": Alice (person) twice, Acme (org), and Alice -> Acme.
_EXTRACTED = ExtractedEntities(
    entities=[
        ExtractedEntity(type="person", name="Alice"),
        ExtractedEntity(type="person", name="alice"),  # case dup -> folds to one canonical row
        ExtractedEntity(type="org", name="Acme"),
    ],
    relations=[ExtractedRelation(src="Alice", relation="works_at", dst="Acme")],
)


def _run[T](coro_fn: Callable[[], Coroutine[Any, Any, T]]) -> T:
    return asyncio.run(coro_fn())


async def _new_tenant(pool: asyncpg.Pool) -> str:
    tid = str(uuid.uuid4())
    await pool.execute("INSERT INTO tenants (id, name) VALUES ($1, $2)", tid, f"t-{tid[:8]}")
    return tid


def test_index_extract_dedup_idempotent_and_purge(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        tid = await _new_tenant(pool)
        current_security.set(SecurityContext(subject_id="test", tenant_id=tid))
        store = PgEntityStore(TenantQuerier(pool))

        async def _fake_extract(text: str, *, provider: Any, model: str) -> ExtractedEntities:
            return _EXTRACTED

        monkeypatch.setattr(entity_indexing, "extract_entities", _fake_extract)
        provider = FakeModelProvider()
        doc = "doc-ner-1"

        await index_document_entities(
            text="...", document_id=doc, store=store, provider=provider, model="m"
        )

        ents = {e.name: e for e in await store.entities_for_document(doc)}
        assert set(ents) == {"Alice", "Acme"}  # the case-dup folded to one Alice
        alice = ents["Alice"]
        assert alice.type == "person" and alice.mention_count == 2  # two mentions folded
        # the relation became an edge Alice -> Acme
        edges = await store.edges_for_entity(alice.id)
        assert ("works_at", ents["Acme"].id) in edges

        # Idempotent: re-indexing the SAME document must NOT inflate mention_count.
        await index_document_entities(
            text="...", document_id=doc, store=store, provider=provider, model="m"
        )
        alice2 = {e.name: e for e in await store.entities_for_document(doc)}["Alice"]
        assert alice2.mention_count == 2

        # Purge the document -> its mentions drop and now-orphan entities are swept (edges cascade).
        await store.purge_document_entities(doc)
        await store.sweep_orphan_entities(grace_hours=0)
        assert await store.entities_for_document(doc) == []
        assert await store.list_entities() == []
        await pool.close()

    _run(run)


def test_failed_extraction_keeps_prior_entities(monkeypatch: pytest.MonkeyPatch) -> None:
    # Data-safety (#464): a FAILED/timed-out extraction must NOT purge a document's existing
    # entities (the purge used to run before extraction, so a timeout wiped the KAG). A raising
    # extractor leaves the prior entities exactly as they were.
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        tid = await _new_tenant(pool)
        current_security.set(SecurityContext(subject_id="test", tenant_id=tid))
        store = PgEntityStore(TenantQuerier(pool))
        provider = FakeModelProvider()
        doc = "doc-ner-safety"

        async def _ok_extract(text: str, *, provider: Any, model: str) -> ExtractedEntities:
            return _EXTRACTED

        monkeypatch.setattr(entity_indexing, "extract_entities", _ok_extract)
        await index_document_entities(
            text="...", document_id=doc, store=store, provider=provider, model="m"
        )
        assert {e.name for e in await store.entities_for_document(doc)} == {"Alice", "Acme"}

        async def _boom_extract(text: str, *, provider: Any, model: str) -> ExtractedEntities:
            raise TimeoutError("model cold-load exceeded the client timeout")

        monkeypatch.setattr(entity_indexing, "extract_entities", _boom_extract)
        # Best-effort: this must swallow the error AND leave the prior entities intact (no purge).
        await index_document_entities(
            text="...", document_id=doc, store=store, provider=provider, model="m"
        )
        assert {e.name for e in await store.entities_for_document(doc)} == {"Alice", "Acme"}
        await pool.close()

    _run(run)
