"""Relational store for folder-source sync state (Documents v2 P1, #456).

Two tables, both tenant-scoped under RLS (migrations 0025/0026):
  * ``folder_sources`` -- registered local folder roots that are continuously scanned;
  * ``folder_files``   -- per-file sync state under a source (the mark-and-sweep work ledger).

The DB is the source of truth for sync state; the in-memory watcher/queue is only an accelerator,
so a crash is recoverable by re-scan. ``folder_files.document_id`` is a SOFT link to ``documents``
(no FK) -- the reconciler owns vector/document deletion, mirroring the ``vectors<->documents``
relationship. Dedup across folders is automatic: identical bytes -> identical content-addressed
``documents.id``, so two file rows resolve to one document.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import asyncpg

from personalai_storage_postgres.db import TENANT_ID_SQL, Querier

# CHECK-constrained status enums (0025/0026). Color mapping for the UI: source idle=green/
# scanning=amber/error=red/disabled=grey; file synced=green / pending|indexing|stale=amber /
# error=red / deleted=grey.
SourceStatus = Literal["idle", "scanning", "error", "disabled"]
FileStatus = Literal["pending", "indexing", "synced", "stale", "error", "deleted"]

_SOURCE_COLS = (
    "id, root_path, label, enabled, recursive, include_globs, exclude_globs, max_file_bytes, "
    "follow_symlinks, status, status_detail, scan_generation, last_scan_started_at, "
    "last_scan_finished_at, created_at, updated_at"
)
_FILE_COLS = (
    "folder_source_id, rel_path, size_bytes, mtime_ns, content_sha256, document_id, status, "
    "error_code, error_detail, last_seen_scan, indexed_at, created_at, updated_at"
)


class FolderExistsError(Exception):
    """Raised when a root path is already registered for this tenant (UNIQUE root_path)."""


@dataclass(frozen=True)
class FolderSource:
    """A registered folder root (tenant-scoped; tenant_id is RLS-implicit, not exposed)."""

    id: str
    root_path: str
    label: str
    enabled: bool
    recursive: bool
    include_globs: list[str]
    exclude_globs: list[str]
    max_file_bytes: int | None
    follow_symlinks: bool
    status: SourceStatus
    status_detail: str | None
    scan_generation: int
    last_scan_started_at: datetime | None
    last_scan_finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class FolderFile:
    """Per-file sync state under a folder source."""

    folder_source_id: str
    rel_path: str
    size_bytes: int
    mtime_ns: int
    content_sha256: str | None
    document_id: str | None
    status: FileStatus
    error_code: str | None
    error_detail: str | None
    last_seen_scan: int
    indexed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PgFolderStore:
    """CRUD + scan/sweep/work-queue operations for folder sources and their files."""

    def __init__(self, pool: Querier) -> None:
        self._pool = pool

    # --- folder_sources -------------------------------------------------------------------------

    async def register(
        self,
        *,
        root_path: str,
        label: str,
        recursive: bool = True,
        include_globs: Sequence[str] = (),
        exclude_globs: Sequence[str] = (),
        max_file_bytes: int | None = None,
        follow_symlinks: bool = False,
    ) -> FolderSource:
        try:
            row = await self._pool.fetchrow(
                f"INSERT INTO folder_sources "
                f"(tenant_id, root_path, label, recursive, include_globs, exclude_globs, "
                f"max_file_bytes, follow_symlinks) "
                f"VALUES ({TENANT_ID_SQL}, $1, $2, $3, $4, $5, $6, $7) "
                f"RETURNING {_SOURCE_COLS}",
                root_path,
                label,
                recursive,
                list(include_globs),
                list(exclude_globs),
                max_file_bytes,
                follow_symlinks,
            )
        except asyncpg.UniqueViolationError as exc:
            raise FolderExistsError(root_path) from exc
        assert row is not None
        return _to_source(row)

    async def list_sources(self) -> list[FolderSource]:
        rows = await self._pool.fetch(
            f"SELECT {_SOURCE_COLS} FROM folder_sources ORDER BY created_at"
        )
        return [_to_source(r) for r in rows]

    async def get_source(self, source_id: str) -> FolderSource | None:
        row = await self._pool.fetchrow(
            f"SELECT {_SOURCE_COLS} FROM folder_sources WHERE id = $1", source_id
        )
        return _to_source(row) if row is not None else None

    async def delete_source(self, source_id: str) -> None:
        # folder_files cascade via the composite FK ON DELETE CASCADE (0026).
        await self._pool.execute("DELETE FROM folder_sources WHERE id = $1", source_id)

    async def set_source_status(
        self, source_id: str, status: SourceStatus, detail: str | None = None
    ) -> None:
        await self._pool.execute(
            "UPDATE folder_sources SET status = $2, status_detail = $3, updated_at = now() "
            "WHERE id = $1",
            source_id,
            status,
            detail,
        )

    async def set_enabled(self, source_id: str, enabled: bool) -> None:
        """Pause/resume a source (#456). `enabled` is the durable "should this be synced" flag,
        distinct from the transient `status`; the watcher/resync honor it."""
        await self._pool.execute(
            "UPDATE folder_sources SET enabled = $2, updated_at = now() WHERE id = $1",
            source_id,
            enabled,
        )

    async def begin_scan(self, source_id: str) -> int:
        """Bump the mark-and-sweep watermark, mark the source scanning, return the generation."""
        row = await self._pool.fetchrow(
            "UPDATE folder_sources "
            "SET scan_generation = scan_generation + 1, status = 'scanning', "
            "last_scan_started_at = now(), updated_at = now() "
            "WHERE id = $1 RETURNING scan_generation",
            source_id,
        )
        assert row is not None
        return int(row["scan_generation"])

    async def finish_scan(self, source_id: str) -> None:
        await self._pool.execute(
            "UPDATE folder_sources SET status = 'idle', last_scan_finished_at = now(), "
            "updated_at = now() WHERE id = $1",
            source_id,
        )

    # --- folder_files: scan / sweep ------------------------------------------------------------

    async def upsert_file(
        self,
        *,
        folder_source_id: str,
        rel_path: str,
        size_bytes: int,
        mtime_ns: int,
        generation: int,
    ) -> None:
        """Mark phase of mark-and-sweep: stamp ``last_seen_scan`` and flag changes (#456).

        The scanner sets only the cheap (size, mtime) fingerprint -- the worker computes the
        authoritative ``content_sha256`` and ``document_id`` at index time, so this never touches
        them. On conflict: a changed fingerprint -> ``stale`` (re-index); a tombstone that
        reappeared within the grace window -> ``pending`` (revive); anything else is left as-is (a
        ``synced`` or ``error`` row whose bytes are unchanged stays put)."""
        await self._pool.execute(
            "INSERT INTO folder_files "
            "(tenant_id, folder_source_id, rel_path, size_bytes, mtime_ns, status, last_seen_scan) "
            f"VALUES ({TENANT_ID_SQL}, $1, $2, $3, $4, 'pending', $5) "
            "ON CONFLICT (tenant_id, folder_source_id, rel_path) DO UPDATE SET "
            "last_seen_scan = EXCLUDED.last_seen_scan, "
            "size_bytes = EXCLUDED.size_bytes, mtime_ns = EXCLUDED.mtime_ns, "
            "status = CASE "
            "  WHEN folder_files.size_bytes <> EXCLUDED.size_bytes "
            "    OR folder_files.mtime_ns <> EXCLUDED.mtime_ns THEN 'stale' "
            "  WHEN folder_files.status = 'deleted' THEN 'pending' "
            "  ELSE folder_files.status END, "
            "updated_at = now()",
            folder_source_id,
            rel_path,
            size_bytes,
            mtime_ns,
            generation,
        )

    async def sweep(self, *, folder_source_id: str, generation: int) -> int:
        """Sweep phase: tombstone files not re-stamped this generation. Returns the count."""
        result = await self._pool.execute(
            "UPDATE folder_files SET status = 'deleted', updated_at = now() "
            "WHERE folder_source_id = $1 AND last_seen_scan < $2 AND status <> 'deleted'",
            folder_source_id,
            generation,
        )
        return _rowcount(result)

    # --- folder_files: work queue --------------------------------------------------------------

    async def claim_next_file(self, folder_source_id: str) -> FolderFile | None:
        """Atomically claim the next pending/stale file (-> ``indexing``) for the embed worker."""
        row = await self._pool.fetchrow(
            "UPDATE folder_files SET status = 'indexing', updated_at = now() "
            "WHERE (tenant_id, folder_source_id, rel_path) = ("
            "  SELECT tenant_id, folder_source_id, rel_path FROM folder_files "
            "  WHERE folder_source_id = $1 AND status IN ('pending', 'stale') "
            "  ORDER BY updated_at FOR UPDATE SKIP LOCKED LIMIT 1"
            f") RETURNING {_FILE_COLS}",
            folder_source_id,
        )
        return _to_file(row) if row is not None else None

    async def mark_file_synced(
        self, *, folder_source_id: str, rel_path: str, document_id: str, content_sha256: str
    ) -> None:
        await self._pool.execute(
            "UPDATE folder_files SET status = 'synced', document_id = $3, content_sha256 = $4, "
            "error_code = NULL, error_detail = NULL, indexed_at = now(), updated_at = now() "
            "WHERE folder_source_id = $1 AND rel_path = $2",
            folder_source_id,
            rel_path,
            document_id,
            content_sha256,
        )

    async def mark_file_error(
        self, *, folder_source_id: str, rel_path: str, error_code: str, error_detail: str
    ) -> None:
        await self._pool.execute(
            "UPDATE folder_files SET status = 'error', error_code = $3, error_detail = $4, "
            "updated_at = now() WHERE folder_source_id = $1 AND rel_path = $2",
            folder_source_id,
            rel_path,
            error_code,
            error_detail[:2000],
        )

    # --- folder_files: read / rollup -----------------------------------------------------------

    async def list_files(
        self,
        *,
        folder_source_id: str,
        status: FileStatus | None = None,
        limit: int = 50,
        after_rel_path: str | None = None,
    ) -> list[FolderFile]:
        """Keyset-paginated file list (stable order by rel_path), optionally filtered by status."""
        clauses = ["folder_source_id = $1"]
        params: list[object] = [folder_source_id]
        if status is not None:
            params.append(status)
            clauses.append(f"status = ${len(params)}")
        if after_rel_path is not None:
            params.append(after_rel_path)
            clauses.append(f"rel_path > ${len(params)}")
        params.append(limit)
        rows = await self._pool.fetch(
            f"SELECT {_FILE_COLS} FROM folder_files WHERE {' AND '.join(clauses)} "
            f"ORDER BY rel_path LIMIT ${len(params)}",
            *params,
        )
        return [_to_file(r) for r in rows]

    async def count_files_by_status(self, folder_source_id: str) -> dict[str, int]:
        """The per-folder rollup the UI shows, e.g. ``{'synced': 312, 'indexing': 4}``."""
        rows = await self._pool.fetch(
            "SELECT status, count(*) AS n FROM folder_files WHERE folder_source_id = $1 "
            "GROUP BY status",
            folder_source_id,
        )
        return {r["status"]: r["n"] for r in rows}

    async def purge_tombstones(self, *, grace_days: int = 7) -> int:
        """Hard-delete tombstoned files older than the grace window (renames revive before this)."""
        result = await self._pool.execute(
            "DELETE FROM folder_files WHERE status = 'deleted' "
            "AND updated_at < now() - make_interval(days => $1)",
            grace_days,
        )
        return _rowcount(result)


def _rowcount(result: str) -> int:
    # asyncpg execute() returns a status string like "UPDATE 3" / "DELETE 0".
    return int(result.split()[-1]) if result and result.split()[-1].isdigit() else 0


def _to_source(row: asyncpg.Record) -> FolderSource:
    return FolderSource(
        id=str(row["id"]),
        root_path=row["root_path"],
        label=row["label"],
        enabled=row["enabled"],
        recursive=row["recursive"],
        include_globs=list(row["include_globs"]),
        exclude_globs=list(row["exclude_globs"]),
        max_file_bytes=row["max_file_bytes"],
        follow_symlinks=row["follow_symlinks"],
        status=row["status"],
        status_detail=row["status_detail"],
        scan_generation=row["scan_generation"],
        last_scan_started_at=row["last_scan_started_at"],
        last_scan_finished_at=row["last_scan_finished_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_file(row: asyncpg.Record) -> FolderFile:
    return FolderFile(
        folder_source_id=str(row["folder_source_id"]),
        rel_path=row["rel_path"],
        size_bytes=row["size_bytes"],
        mtime_ns=row["mtime_ns"],
        content_sha256=row["content_sha256"],
        document_id=row["document_id"],
        status=row["status"],
        error_code=row["error_code"],
        error_detail=row["error_detail"],
        last_seen_scan=row["last_seen_scan"],
        indexed_at=row["indexed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
