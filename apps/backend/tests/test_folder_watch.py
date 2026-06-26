"""Live folder watcher manager (Documents v2 P1, #456).

DB-gated. Tests the manager's reconcile path (enumerate enabled sources -> sync each under its
tenant context) — what the startup + safety-net loops and every debounced FS event ultimately run.
The watchdog observer start/stop is exercised by the full-app boot in test_folders_api.py.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable, Coroutine
from collections.abc import Sequence as Seq
from pathlib import Path
from typing import Any

import pytest

from personalai_backend.folder_watch import FolderSyncManager
from personalai_backend.tenant_querier import TenantQuerier
from personalai_contracts.ports import EmbeddingResult, ModelProvider, SecurityContext
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig
from personalai_core.security import current_security
from personalai_storage_postgres import (
    VECTOR_DIM,
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


pytestmark = pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")

_CONFIG = CoreConfig(embed_provider="fake", embed_model="fake-embed")


class _LocalEmbed(FakeModelProvider):
    _host = "127.0.0.1"

    async def embed(self, texts: Seq[str], model: str) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[0.0] * (VECTOR_DIM - 1) + [1.0] for _ in texts],
            model=model,
            dimensions=VECTOR_DIM,
        )


def _run[T](coro_fn: Callable[[], Coroutine[Any, Any, T]]) -> T:
    return asyncio.run(coro_fn())


def test_manager_reconcile_indexes_registered_source(tmp_path: Path) -> None:
    async def run() -> None:
        pool = await create_pool(DB_URL)
        await apply_migrations(pool)
        tid = str(uuid.uuid4())
        await pool.execute("INSERT INTO tenants (id, name) VALUES ($1, $2)", tid, f"t-{tid[:8]}")
        current_security.set(SecurityContext(subject_id="test", tenant_id=tid))
        store = PgFolderStore(TenantQuerier(pool))
        docs = PgDocumentStore(TenantQuerier(pool))
        (tmp_path / "note.txt").write_text("watched content")
        src = await store.register(root_path=str(tmp_path), label="Watched")

        provider: ModelProvider = _LocalEmbed()
        manager = FolderSyncManager(pool, _CONFIG, lambda _name: provider)
        # reconcile enumerates enabled sources (owner conn) and syncs each under its tenant context.
        await manager.reconcile()

        # reconcile sets a per-source context, so re-bind OUR tenant before reading (RLS).
        current_security.set(SecurityContext(subject_id="test", tenant_id=tid))
        files = await store.list_files(folder_source_id=src.id)
        assert len(files) == 1 and files[0].status == "synced"
        assert files[0].document_id is not None
        assert await docs.get(files[0].document_id) is not None  # indexed into the global corpus
        await pool.close()

    _run(run)
