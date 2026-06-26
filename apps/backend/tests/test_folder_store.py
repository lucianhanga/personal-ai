"""Folder-sync data layer (Documents v2 P1, #456): PgFolderStore + the refcount GC.

DB-gated (real Postgres, skipped otherwise). Exercises the store directly through a tenant-bound
``TenantQuerier`` (RLS), mirroring how the app wires it. No embeddings/Ollama needed -- these tests
are pure relational state-machine + refcount checks.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import asyncpg
import pytest

from personalai_backend.ingestion import content_document_id
from personalai_backend.tenant_querier import TenantQuerier
from personalai_contracts.ports import SecurityContext
from personalai_contracts.ports.storage import GLOBAL_SCOPE
from personalai_core.security import current_security
from personalai_storage_postgres import (
    FolderExistsError,
    PgDocumentStore,
    PgFolderStore,
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


def _run[T](coro_fn: Callable[[], Coroutine[Any, Any, T]]) -> T:
    return asyncio.run(coro_fn())


async def _new_tenant(pool: asyncpg.Pool) -> str:
    # Owner connection bypasses RLS; seed a fresh tenant for isolation tests.
    tid = str(uuid.uuid4())
    await pool.execute("INSERT INTO tenants (id, name) VALUES ($1, $2)", tid, f"t-{tid[:8]}")
    return tid


def _bind(tenant_id: str) -> None:
    current_security.set(SecurityContext(subject_id="test", tenant_id=tenant_id))


def test_register_and_unique_root_path() -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        tid = await _new_tenant(pool)
        _bind(tid)
        store = PgFolderStore(TenantQuerier(pool))
        root = f"/tmp/docs-{uuid.uuid4().hex[:8]}"
        src = await store.register(root_path=root, label="Docs")
        assert src.status == "idle" and src.scan_generation == 0 and src.label == "Docs"
        # UNIQUE(tenant_id, root_path) -> typed error on a duplicate.
        with pytest.raises(FolderExistsError):
            await store.register(root_path=root, label="Dup")
        assert [s.id for s in await store.list_sources()] == [src.id]
        await pool.close()

    _run(run)


def test_begin_scan_bumps_generation_and_status() -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        _bind(await _new_tenant(pool))
        store = PgFolderStore(TenantQuerier(pool))
        src = await store.register(root_path=f"/tmp/g-{uuid.uuid4().hex[:8]}", label="G")
        g1 = await store.begin_scan(src.id)
        g2 = await store.begin_scan(src.id)
        assert g1 == 1 and g2 == 2
        scanning = await store.get_source(src.id)
        assert scanning is not None and scanning.status == "scanning"
        await store.finish_scan(src.id)
        done = await store.get_source(src.id)
        assert done is not None and done.status == "idle"
        await pool.close()

    _run(run)


def test_upsert_file_lifecycle() -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        _bind(await _new_tenant(pool))
        store = PgFolderStore(TenantQuerier(pool))
        src = await store.register(root_path=f"/tmp/l-{uuid.uuid4().hex[:8]}", label="L")
        gen = await store.begin_scan(src.id)
        await store.upsert_file(
            folder_source_id=src.id, rel_path="a.txt", size_bytes=10, mtime_ns=100, generation=gen
        )
        files = await store.list_files(folder_source_id=src.id)
        assert len(files) == 1 and files[0].status == "pending"

        # Same fingerprint, next scan -> stays pending (no spurious re-index), last_seen_scan bumps.
        gen2 = await store.begin_scan(src.id)
        await store.upsert_file(
            folder_source_id=src.id, rel_path="a.txt", size_bytes=10, mtime_ns=100, generation=gen2
        )
        f = (await store.list_files(folder_source_id=src.id))[0]
        assert f.status == "pending" and f.last_seen_scan == gen2

        # Mark it synced, then a CHANGED fingerprint -> stale.
        await store.mark_file_synced(
            folder_source_id=src.id, rel_path="a.txt", document_id="d1", content_sha256="sha"
        )
        gen3 = await store.begin_scan(src.id)
        await store.upsert_file(
            folder_source_id=src.id, rel_path="a.txt", size_bytes=20, mtime_ns=200, generation=gen3
        )
        assert (await store.list_files(folder_source_id=src.id))[0].status == "stale"

        # Tombstone then reappear -> revive to pending.
        await store.sweep(folder_source_id=src.id, generation=gen3 + 5)
        assert (await store.list_files(folder_source_id=src.id))[0].status == "deleted"
        gen4 = await store.begin_scan(src.id)
        await store.upsert_file(
            folder_source_id=src.id, rel_path="a.txt", size_bytes=20, mtime_ns=200, generation=gen4
        )
        assert (await store.list_files(folder_source_id=src.id))[0].status == "pending"
        await pool.close()

    _run(run)


def test_sweep_tombstones_only_unseen() -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        _bind(await _new_tenant(pool))
        store = PgFolderStore(TenantQuerier(pool))
        src = await store.register(root_path=f"/tmp/s-{uuid.uuid4().hex[:8]}", label="S")
        gen = await store.begin_scan(src.id)
        for name in ("keep.txt", "gone.txt"):
            await store.upsert_file(
                folder_source_id=src.id, rel_path=name, size_bytes=1, mtime_ns=1, generation=gen
            )
        # Next scan re-stamps only keep.txt.
        gen2 = await store.begin_scan(src.id)
        await store.upsert_file(
            folder_source_id=src.id, rel_path="keep.txt", size_bytes=1, mtime_ns=1, generation=gen2
        )
        swept = await store.sweep(folder_source_id=src.id, generation=gen2)
        assert swept == 1
        by_status = await store.count_files_by_status(src.id)
        assert by_status.get("deleted") == 1 and by_status.get("pending") == 1
        await pool.close()

    _run(run)


def test_claim_next_file_transitions_to_indexing() -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        _bind(await _new_tenant(pool))
        store = PgFolderStore(TenantQuerier(pool))
        src = await store.register(root_path=f"/tmp/c-{uuid.uuid4().hex[:8]}", label="C")
        gen = await store.begin_scan(src.id)
        await store.upsert_file(
            folder_source_id=src.id, rel_path="only.txt", size_bytes=1, mtime_ns=1, generation=gen
        )
        claimed = await store.claim_next_file(src.id)
        assert claimed is not None
        assert claimed.rel_path == "only.txt" and claimed.status == "indexing"
        # Nothing left pending/stale.
        assert await store.claim_next_file(src.id) is None
        await pool.close()

    _run(run)


def test_list_files_pagination_and_status_filter() -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        _bind(await _new_tenant(pool))
        store = PgFolderStore(TenantQuerier(pool))
        src = await store.register(root_path=f"/tmp/p-{uuid.uuid4().hex[:8]}", label="P")
        gen = await store.begin_scan(src.id)
        for i in range(5):
            await store.upsert_file(
                folder_source_id=src.id, rel_path=f"{i}.txt", size_bytes=1, mtime_ns=1,
                generation=gen,
            )
        await store.mark_file_synced(
            folder_source_id=src.id, rel_path="0.txt", document_id="d", content_sha256="s"
        )
        page1 = await store.list_files(folder_source_id=src.id, limit=2)
        assert [f.rel_path for f in page1] == ["0.txt", "1.txt"]
        page2 = await store.list_files(folder_source_id=src.id, limit=2, after_rel_path="1.txt")
        assert [f.rel_path for f in page2] == ["2.txt", "3.txt"]
        synced = await store.list_files(folder_source_id=src.id, status="synced")
        assert [f.rel_path for f in synced] == ["0.txt"]
        await pool.close()

    _run(run)


def test_gc_orphans_refcount_and_pin() -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        _bind(await _new_tenant(pool))
        q = TenantQuerier(pool)
        folders, docs = PgFolderStore(q), PgDocumentStore(q)
        src = await folders.register(root_path=f"/tmp/gc-{uuid.uuid4().hex[:8]}", label="GC")

        pinned = content_document_id(uuid.uuid4().bytes)  # a manual upload (manual_pin stays true)
        synced = content_document_id(uuid.uuid4().bytes)  # a folder-synced doc with a live ref
        await docs.add(id=pinned, name="m.txt", mime="text/plain", size_bytes=1, chunk_count=1)
        await docs.add(
            id=synced, name="f.txt", mime="text/plain", size_bytes=1, chunk_count=2,
            scope=GLOBAL_SCOPE, manual_pin=False,
        )
        gen = await folders.begin_scan(src.id)
        await folders.upsert_file(
            folder_source_id=src.id, rel_path="f.txt", size_bytes=1, mtime_ns=1, generation=gen
        )
        await folders.mark_file_synced(
            folder_source_id=src.id, rel_path="f.txt", document_id=synced, content_sha256="s"
        )
        # A live folder_file references `synced`, and `pinned` is manual -> neither is GC-eligible.
        orphans: dict[str, int] = dict(await docs.gc_orphans())
        assert synced not in orphans and pinned not in orphans

        # Tombstone the file -> `synced` now has no LIVE ref -> GC-eligible with its chunk_count.
        await folders.sweep(folder_source_id=src.id, generation=gen + 1)
        orphans2: dict[str, int] = dict(await docs.gc_orphans())
        assert orphans2.get(synced) == 2 and pinned not in orphans2
        await pool.close()

    _run(run)


def test_purge_tombstones_respects_grace_window() -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        _bind(await _new_tenant(pool))
        store = PgFolderStore(TenantQuerier(pool))
        src = await store.register(root_path=f"/tmp/t-{uuid.uuid4().hex[:8]}", label="T")
        gen = await store.begin_scan(src.id)
        await store.upsert_file(
            folder_source_id=src.id, rel_path="x.txt", size_bytes=1, mtime_ns=1, generation=gen
        )
        await store.sweep(folder_source_id=src.id, generation=gen + 1)  # -> deleted, updated_at=now
        # Within the grace window: not purged.
        assert await store.purge_tombstones(grace_days=7) == 0
        assert (await store.list_files(folder_source_id=src.id))[0].status == "deleted"
        # grace_days=0 -> older than now() - 0 is everything in the past -> purged.
        assert await store.purge_tombstones(grace_days=0) == 1
        assert await store.list_files(folder_source_id=src.id) == []
        await pool.close()

    _run(run)


def test_tenant_isolation() -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        tenant_a, tenant_b = await _new_tenant(pool), await _new_tenant(pool)
        store = PgFolderStore(TenantQuerier(pool))

        _bind(tenant_a)
        a_src = await store.register(root_path=f"/tmp/iso-{uuid.uuid4().hex[:8]}", label="A")
        assert len(await store.list_sources()) == 1

        _bind(tenant_b)
        assert await store.list_sources() == []  # A's source invisible to B (RLS)
        assert await store.get_source(a_src.id) is None
        await pool.close()

    _run(run)
