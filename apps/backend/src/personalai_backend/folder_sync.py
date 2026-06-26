"""Folder-source sync orchestration (#456): scan -> mark-and-sweep -> embed worker -> orphan GC.

The DB (``folder_files``) is authoritative; a crash is recoverable by re-scan, so these are pure
orchestration over :class:`PgFolderStore` + the existing ingest pipeline and are unit-testable
against real Postgres with no watcher. The live watchdog accelerator (folder_watch) sits ON TOP of
these and only schedules calls into them.

Local-provider-only, fail-closed: a background sync NEVER egresses — the interactive egress-approval
gate cannot mediate a headless task — so the embed provider is asserted loopback first.

Tenant scoping: every store passed in is a tenant-bound ``Querier`` (RLS via ``app.tenant_id``); the
caller (a request, or the manager setting a per-tenant SecurityContext) owns that binding.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlparse

from personalai_backend.folder_scan import canonical_root, is_contained, iter_indexable_files
from personalai_backend.ingestion import chunk_ids, content_document_id, ingest_text
from personalai_contracts.ports import ModelProvider, VectorRepository
from personalai_contracts.ports.storage import GLOBAL_SCOPE
from personalai_core import CoreConfig
from personalai_core.security.egress import _is_loopback
from personalai_modality_files import UnsupportedFileTypeError, parse_document
from personalai_storage_postgres.document_store import PgDocumentStore
from personalai_storage_postgres.entity_store import PgEntityStore
from personalai_storage_postgres.folder_store import FolderSource, PgFolderStore

# Best-effort NER hook (#451): called (text, document_id) after a NEW global document is ingested,
# so the caller can extract entities into the KAG store. None disables it (e.g. orchestration test).
EntityIndexer = Callable[[str, str], Awaitable[None]]

logger = logging.getLogger(__name__)

_DETAIL_CAP = 500  # cap stored error detail so a noisy exception can't bloat a row


class FolderSyncError(RuntimeError):
    """A folder sync was refused outright (e.g. a non-loopback embed provider would egress)."""


def assert_local_provider(provider: ModelProvider) -> None:
    """Fail-closed: the background-sync embed provider MUST be loopback (no egress). A remote one
    is refused: the interactive egress-approval gate cannot mediate a headless sync task."""
    raw = getattr(provider, "_host", None) or getattr(provider, "_base", None)
    host: str | None = None
    if raw:
        s = str(raw)
        host = urlparse(s).hostname if "://" in s else s
    if host is None or not _is_loopback(host):
        raise FolderSyncError(
            f"folder sync requires a loopback embed provider; refusing egress to host={host!r}"
        )


async def scan_source(store: PgFolderStore, source: FolderSource) -> int:
    """Walk ``source``'s root and mark-and-sweep ``folder_files`` to a fresh scan generation:
    new/changed files become pending/stale, vanished files are tombstoned. Returns files seen.

    The filesystem walk (blocking IO) runs in a thread so a large folder can't stall the loop; the
    per-file upserts run on the event loop (cheap). On any failure the source is set ``error``."""
    gen = await store.begin_scan(source.id)
    try:
        entries = await asyncio.to_thread(
            lambda: list(
                iter_indexable_files(
                    source.root_path,
                    recursive=source.recursive,
                    include_globs=tuple(source.include_globs),
                    exclude_globs=tuple(source.exclude_globs),
                    max_file_bytes=source.max_file_bytes,
                    follow_symlinks=source.follow_symlinks,
                )
            )
        )
        for entry in entries:
            await store.upsert_file(
                folder_source_id=source.id,
                rel_path=entry.rel_path,
                size_bytes=entry.size_bytes,
                mtime_ns=entry.mtime_ns,
                generation=gen,
            )
        await store.sweep(folder_source_id=source.id, generation=gen)
        await store.finish_scan(source.id)
    except Exception as exc:  # noqa: BLE001 - surface to the source status, re-raise for the caller
        await store.set_source_status(source.id, "error", str(exc)[:_DETAIL_CAP])
        raise
    return len(entries)


async def _ingest_file_row(
    store: PgFolderStore,
    docstore: PgDocumentStore,
    vectors: VectorRepository,
    *,
    provider: ModelProvider,
    config: CoreConfig,
    source: FolderSource,
    rel_path: str,
    entity_indexer: EntityIndexer | None = None,
) -> None:
    """Index ONE claimed file: re-check containment, read bytes, content-hash, dedup, embed, link.

    Idempotent + dedup: the document id is the content hash, so a file already embedded (same bytes,
    possibly in another folder) is just re-linked, never re-embedded. Failures mark the file row."""
    root = canonical_root(source.root_path)
    path = root / rel_path
    if not is_contained(path, root):  # defense-in-depth: a symlink may have changed since the scan
        await store.mark_file_error(
            folder_source_id=source.id,
            rel_path=rel_path,
            error_code="E_FOLDER_FORBIDDEN",
            error_detail="path escapes the granted root",
        )
        return
    try:
        content = await asyncio.to_thread(path.read_bytes)
    except OSError as exc:
        await store.mark_file_error(
            folder_source_id=source.id,
            rel_path=rel_path,
            error_code="E_FILE_LOCKED",
            error_detail=str(exc)[:_DETAIL_CAP],
        )
        return

    sha = hashlib.sha256(content).hexdigest()
    document_id = content_document_id(content)
    name = Path(rel_path).name

    if await docstore.get(document_id) is None:  # not yet embedded anywhere -> parse + embed once
        try:
            parsed = await asyncio.to_thread(parse_document, content, name)
        except UnsupportedFileTypeError as exc:
            await store.mark_file_error(
                folder_source_id=source.id,
                rel_path=rel_path,
                error_code="E_FILE_UNSUPPORTED",
                error_detail=str(exc)[:_DETAIL_CAP],
            )
            return
        result = await ingest_text(
            text=parsed.text,
            name=name,
            document_id=document_id,
            embed_model=config.embed_model,
            provider=provider,
            vectors=vectors,
            scope=GLOBAL_SCOPE,
        )
        await docstore.add(
            id=document_id,
            name=name,
            mime=parsed.mime,
            size_bytes=len(content),
            chunk_count=result.chunk_count,
            manual_pin=False,  # folder-synced -> GC-eligible when no live folder_files reference it
        )
        # NER into the KAG store (#451), best-effort, only on a NEW ingest (a dedup re-link already
        # has its entities). The indexer swallows its own errors so it can never fail the sync.
        if entity_indexer is not None:
            await entity_indexer(parsed.text, document_id)
    await store.mark_file_synced(
        folder_source_id=source.id,
        rel_path=rel_path,
        document_id=document_id,
        content_sha256=sha,
    )


async def drain_source(
    store: PgFolderStore,
    docstore: PgDocumentStore,
    vectors: VectorRepository,
    *,
    provider: ModelProvider,
    config: CoreConfig,
    source: FolderSource,
    max_files: int | None = None,
    entity_indexer: EntityIndexer | None = None,
) -> int:
    """Process the pending/stale work queue for one source until empty (or ``max_files``). One bad
    file marks its row ``error`` and never blocks the queue. Returns the count processed."""
    assert_local_provider(provider)  # fail-closed BEFORE any embed call
    processed = 0
    while max_files is None or processed < max_files:
        claimed = await store.claim_next_file(source.id)
        if claimed is None:
            break
        try:
            await _ingest_file_row(
                store,
                docstore,
                vectors,
                provider=provider,
                config=config,
                source=source,
                rel_path=claimed.rel_path,
                entity_indexer=entity_indexer,
            )
        except Exception as exc:  # noqa: BLE001 - best-effort; isolate a bad file from the queue
            logger.warning("folder sync: ingest failed for %r", claimed.rel_path, exc_info=True)
            await store.mark_file_error(
                folder_source_id=source.id,
                rel_path=claimed.rel_path,
                error_code="E_INGEST",
                error_detail=str(exc)[:_DETAIL_CAP],
            )
        processed += 1
    return processed


async def purge_orphans(
    store: PgFolderStore,
    docstore: PgDocumentStore,
    vectors: VectorRepository,
    *,
    grace_days: int = 7,
    entity_store: PgEntityStore | None = None,
) -> int:
    """Refcount GC: delete the vectors + document rows of unpinned global docs that no live
    ``folder_files`` row references, then hard-delete tombstones past the grace window. Returns the
    number of documents purged. Safe to re-run (idempotent set-difference). When an ``entity_store``
    is given, each purged document's entity mentions are dropped and orphans swept (#451)."""
    orphans = await docstore.gc_orphans()
    for document_id, chunk_count in orphans:
        await vectors.delete(chunk_ids(document_id, chunk_count))
        await docstore.delete(document_id)
        if entity_store is not None:
            await entity_store.purge_document_entities(document_id)
    await store.purge_tombstones(grace_days=grace_days)
    if entity_store is not None and orphans:
        await entity_store.sweep_orphan_entities()
    return len(orphans)


async def sync_source(
    store: PgFolderStore,
    docstore: PgDocumentStore,
    vectors: VectorRepository,
    *,
    provider: ModelProvider,
    config: CoreConfig,
    source: FolderSource,
    entity_indexer: EntityIndexer | None = None,
    entity_store: PgEntityStore | None = None,
) -> tuple[int, int]:
    """Full one-shot sync of a source: scan (mark-and-sweep) -> drain the queue -> GC orphans.
    Returns ``(files_seen, files_processed)``. This is what register / resync invoke. The NER
    hooks index entities for new docs and purge them for orphaned docs (#451)."""
    seen = await scan_source(store, source)
    processed = await drain_source(
        store,
        docstore,
        vectors,
        provider=provider,
        config=config,
        source=source,
        entity_indexer=entity_indexer,
    )
    await purge_orphans(store, docstore, vectors, entity_store=entity_store)
    return seen, processed
