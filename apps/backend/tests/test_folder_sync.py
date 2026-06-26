"""Folder-sync orchestration (Documents v2 P1, #456): scan -> drain -> GC, end to end.

DB-gated (real Postgres). Uses a LOOPBACK fake embedder sized to the pgvector column, so no Ollama
is needed but the local-provider fail-closed guard still passes. Exercises the real ingest pipeline:
scan marks files, drain embeds them into the GLOBAL corpus (manual_pin=false), dedup collapses the
same content across folders, and the refcount GC purges a doc only once nothing references it.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable, Coroutine
from collections.abc import Sequence as Seq
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from personalai_backend.folder_sync import (
    FolderSyncError,
    assert_local_provider,
    drain_source,
    purge_orphans,
    scan_source,
    sync_source,
)
from personalai_backend.tenant_querier import TenantQuerier
from personalai_contracts.ports import EmbeddingResult, SecurityContext
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig
from personalai_core.security import current_security
from personalai_storage_postgres import (
    VECTOR_DIM,
    PgDocumentStore,
    PgFolderStore,
    PgVectorRepository,
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

_CONFIG = CoreConfig(embed_provider="fake", embed_model="fake-embed")


class _LocalEmbed(FakeModelProvider):
    """A loopback embedder (passes the fail-closed guard) sized to the pgvector column."""

    _host = "127.0.0.1"

    async def embed(self, texts: Seq[str], model: str) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[0.0] * (VECTOR_DIM - 1) + [1.0] for _ in texts],
            model=model,
            dimensions=VECTOR_DIM,
        )


class _RemoteEmbed(_LocalEmbed):
    """A non-loopback embedder: the guard must refuse it (no background egress)."""

    _host = "api.openai.com"


def _run[T](coro_fn: Callable[[], Coroutine[Any, Any, T]]) -> T:
    return asyncio.run(coro_fn())


async def _new_tenant(pool: asyncpg.Pool) -> str:
    tid = str(uuid.uuid4())
    await pool.execute("INSERT INTO tenants (id, name) VALUES ($1, $2)", tid, f"t-{tid[:8]}")
    return tid


def _bind(tenant_id: str) -> None:
    current_security.set(SecurityContext(subject_id="test", tenant_id=tenant_id))


def _stores(pool: asyncpg.Pool) -> tuple[PgFolderStore, PgDocumentStore, PgVectorRepository]:
    q = TenantQuerier(pool)
    return PgFolderStore(q), PgDocumentStore(q), PgVectorRepository(q)


def test_assert_local_provider_guard() -> None:
    assert_local_provider(_LocalEmbed())  # loopback -> ok
    with pytest.raises(FolderSyncError):
        assert_local_provider(_RemoteEmbed())  # remote -> refused
    with pytest.raises(FolderSyncError):
        assert_local_provider(FakeModelProvider())  # unknown host -> fail-closed


def test_scan_marks_new_files_and_sweeps_deletes(tmp_path: Path) -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        _bind(await _new_tenant(pool))
        store, _, _ = _stores(pool)
        (tmp_path / "a.txt").write_text("alpha")
        (tmp_path / "b.md").write_text("# bravo")
        src = await store.register(root_path=str(tmp_path), label="S")
        seen = await scan_source(store, await _reget(store, src.id))
        assert seen == 2
        files = await store.list_files(folder_source_id=src.id)
        assert {f.rel_path for f in files} == {"a.txt", "b.md"}
        assert all(f.status == "pending" for f in files)
        # Delete one file on disk, re-scan -> it is tombstoned (the other stays pending).
        (tmp_path / "a.txt").unlink()
        await scan_source(store, await _reget(store, src.id))
        by_path = {f.rel_path: f.status for f in await store.list_files(folder_source_id=src.id)}
        assert by_path["a.txt"] == "deleted"
        assert by_path["b.md"] == "pending"
        await pool.close()

    _run(run)


def test_sync_indexes_global_corpus_and_dedups(tmp_path: Path) -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        _bind(await _new_tenant(pool))
        store, docs, vectors = _stores(pool)
        provider = _LocalEmbed()
        body = "Lisbon is the capital of Portugal. " * 10
        f1 = tmp_path / "one"
        f1.mkdir()
        (f1 / "geo.txt").write_text(body)
        src1 = await store.register(root_path=str(f1), label="One")
        seen, processed = await sync_source(
            store,
            docs,
            vectors,
            provider=provider,
            config=_CONFIG,
            source=await _reget(store, src1.id),
        )
        assert (seen, processed) == (1, 1)
        file1 = (await store.list_files(folder_source_id=src1.id))[0]
        assert file1.status == "synced" and file1.document_id is not None
        doc = await docs.get(file1.document_id)
        assert doc is not None and doc.manual_pin is False and doc.chunk_count > 0
        assert doc in await docs.list()  # surfaces in the GLOBAL Settings->Documents corpus

        # A SECOND folder with identical content dedups to the SAME document (no re-embed).
        f2 = tmp_path / "two"
        f2.mkdir()
        (f2 / "copy.txt").write_text(body)
        src2 = await store.register(root_path=str(f2), label="Two")
        await sync_source(
            store,
            docs,
            vectors,
            provider=provider,
            config=_CONFIG,
            source=await _reget(store, src2.id),
        )
        file2 = (await store.list_files(folder_source_id=src2.id))[0]
        assert file2.document_id == file1.document_id  # same content-hash id
        assert len(await docs.list()) == 1  # one document, two folder references
        await pool.close()

    _run(run)


def test_purge_orphans_respects_refcount(tmp_path: Path) -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        _bind(await _new_tenant(pool))
        store, docs, vectors = _stores(pool)
        provider = _LocalEmbed()
        (tmp_path / "doc.txt").write_text("ephemeral content here")
        src = await store.register(root_path=str(tmp_path), label="P")
        await sync_source(
            store,
            docs,
            vectors,
            provider=provider,
            config=_CONFIG,
            source=await _reget(store, src.id),
        )
        doc_id = (await store.list_files(folder_source_id=src.id))[0].document_id
        assert doc_id is not None and await docs.get(doc_id) is not None

        # Still referenced (status synced) -> GC must NOT purge it.
        assert await purge_orphans(store, docs, vectors) == 0
        assert await docs.get(doc_id) is not None

        # Delete on disk + re-scan -> tombstoned; nothing live references the doc -> GC purges it.
        (tmp_path / "doc.txt").unlink()
        await scan_source(store, await _reget(store, src.id))
        purged = await purge_orphans(store, docs, vectors)
        assert purged == 1
        assert await docs.get(doc_id) is None  # vectors + document row gone
        await pool.close()

    _run(run)


def test_drain_fail_closed_on_remote_provider(tmp_path: Path) -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        _bind(await _new_tenant(pool))
        store, docs, vectors = _stores(pool)
        (tmp_path / "x.txt").write_text("data")
        src = await store.register(root_path=str(tmp_path), label="R")
        await scan_source(store, await _reget(store, src.id))
        # A remote embed provider must be refused BEFORE any work (no background egress).
        with pytest.raises(FolderSyncError):
            await drain_source(
                store,
                docs,
                vectors,
                provider=_RemoteEmbed(),
                config=_CONFIG,
                source=await _reget(store, src.id),
            )
        await pool.close()

    _run(run)


async def _reget(store: PgFolderStore, source_id: str) -> Any:
    src = await store.get_source(source_id)
    assert src is not None
    return src
