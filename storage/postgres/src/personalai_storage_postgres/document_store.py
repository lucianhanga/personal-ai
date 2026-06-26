"""Relational store for ingested documents (ADR-0005)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import asyncpg

from personalai_contracts.ports.storage import GLOBAL_SCOPE, Scope
from personalai_storage_postgres.db import TENANT_ID_SQL, Querier, scope_predicate

_COLS = "id, name, mime, size_bytes, chunk_count, created_at, manual_pin"


@dataclass(frozen=True)
class Document:
    """Metadata about an ingested file."""

    id: str
    name: str
    mime: str
    size_bytes: int
    chunk_count: int
    created_at: datetime
    # #456: manual uploads are pinned (never auto-purged by the folder reconciler); folder-synced
    # docs are unpinned and GC-eligible once no live folder_files row references them.
    manual_pin: bool = True


class PgDocumentStore:
    """CRUD for the ``documents`` table."""

    def __init__(self, pool: Querier) -> None:
        self._pool = pool

    async def add(
        self,
        *,
        id: str,
        name: str,
        mime: str,
        size_bytes: int,
        chunk_count: int,
        scope: Scope = GLOBAL_SCOPE,
        manual_pin: bool = True,
    ) -> Document:
        # Scope columns are bound params (6, 7); NULL/NULL = the global corpus. manual_pin ($8)
        # defaults true so /files uploads stay pinned; the folder worker passes False (#456).
        row = await self._pool.fetchrow(
            f"INSERT INTO documents "
            f"(id, name, mime, size_bytes, chunk_count, tenant_id, conversation_id, project_id, "
            f"manual_pin) "
            f"VALUES ($1, $2, $3, $4, $5, {TENANT_ID_SQL}, $6, $7, $8) "
            f"RETURNING {_COLS}",
            id,
            name,
            mime,
            size_bytes,
            chunk_count,
            scope.conversation_id,
            scope.project_id,
            manual_pin,
        )
        assert row is not None
        return _to_document(row)

    async def list(
        self, *, scope: Scope = GLOBAL_SCOPE, manual_only: bool = False
    ) -> list[Document]:
        # The global default adds `conversation_id IS NULL AND project_id IS NULL` so ephemeral /
        # project documents never surface in the Settings -> Documents listing (anti-bleed, #420).
        # ``manual_only`` further restricts to manual uploads (manual_pin=true) so folder-synced
        # docs (manual_pin=false) do NOT appear in the "Individual uploads" list (#451).
        predicate, params = scope_predicate(scope, next_param=1)
        if manual_only:
            predicate += " AND manual_pin = true"
        rows = await self._pool.fetch(
            f"SELECT {_COLS} FROM documents WHERE {predicate} ORDER BY created_at DESC",
            *params,
        )
        return [_to_document(r) for r in rows]

    async def get(self, document_id: str) -> Document | None:
        row = await self._pool.fetchrow(
            f"SELECT {_COLS} FROM documents WHERE id = $1",
            document_id,
        )
        return _to_document(row) if row is not None else None

    async def delete(self, document_id: str) -> None:
        await self._pool.execute("DELETE FROM documents WHERE id = $1", document_id)

    async def gc_orphans(self) -> Sequence[tuple[str, int]]:
        """Return ``(document_id, chunk_count)`` for GC-eligible folder-synced documents (#456).

        A global document is purgeable only when it is unpinned (not a manual upload) AND no LIVE
        ``folder_files`` row still references it (tombstoned holders, ``status='deleted'``, do not
        count). The caller deletes each doc's vectors via ``chunk_ids(document_id, count)`` then
        ``delete(document_id)``. RLS-scoped: ``current_setting('app.tenant_id')`` confines the scan
        to the bound tenant, so this is safe on the tenant-bound querier."""
        rows = await self._pool.fetch(
            "SELECT d.id, d.chunk_count FROM documents d "
            "WHERE d.tenant_id = current_setting('app.tenant_id')::uuid "
            "AND d.manual_pin = false AND d.conversation_id IS NULL AND d.project_id IS NULL "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM folder_files ff "
            "  WHERE ff.tenant_id = d.tenant_id AND ff.document_id = d.id "
            "  AND ff.status <> 'deleted'"
            ")",
        )
        return [(r["id"], r["chunk_count"]) for r in rows]


def _to_document(row: asyncpg.Record) -> Document:
    return Document(
        id=row["id"],
        name=row["name"],
        mime=row["mime"],
        size_bytes=row["size_bytes"],
        chunk_count=row["chunk_count"],
        created_at=row["created_at"],
        manual_pin=row["manual_pin"],
    )
