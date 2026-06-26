"""Live folder watcher (#456): watchdog observers + debounce over the DB-authoritative sync engine.

The watcher only ACCELERATES; ``folder_sync`` stays authoritative, so a dropped OS event or a crash
is recovered by the periodic safety-net reconcile and the startup reconcile. One observer
per enabled source root; a burst of filesystem events is coalesced per root into a single
``sync_source`` run under that source's tenant context. Local-first, single process.

Enumeration uses the raw (owner) pool, which bypasses RLS, to see every tenant's sources; each sync
then drops to a tenant-bound ``TenantQuerier`` under the source's ``app.tenant_id`` (RLS-scoped).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any

import asyncpg
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from personalai_backend.entity_indexing import index_document_entities
from personalai_backend.folder_sync import FolderSyncError, sync_source
from personalai_backend.tenant_querier import TenantQuerier
from personalai_contracts.ports import ModelProvider, SecurityContext
from personalai_core import CoreConfig
from personalai_core.security import current_security
from personalai_storage_postgres import (
    PgDocumentStore,
    PgEntityStore,
    PgFolderStore,
    PgVectorRepository,
)

logger = logging.getLogger(__name__)

_DEBOUNCE_S = 2.0  # coalesce a burst of FS events for one root into a single sync
_SAFETY_NET_S = 600.0  # periodic full reconcile catches OS events the watcher dropped


class _SourceHandler(FileSystemEventHandler):
    """Bridges watchdog's observer THREAD to the event loop: any file change (not a bare directory
    event) is marshalled to the loop via ``call_soon_threadsafe`` for debouncing. ``call_later`` is
    not thread-safe, so the hop through ``call_soon_threadsafe`` is mandatory."""

    def __init__(self, loop: asyncio.AbstractEventLoop, on_change: Callable[[], None]) -> None:
        self._loop = loop
        self._on_change = on_change

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return  # directory events are redundant — the contained file events cover the change
        self._loop.call_soon_threadsafe(self._on_change)


class FolderSyncManager:
    """Owns the watchdog observer + per-root debounce, turning filesystem changes into tenant-scoped
    ``sync_source`` runs. Built once in the app lifespan with the raw pool, the config, and the
    provider resolver; ``start`` is non-blocking (the initial reconcile runs in the background)."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        config: CoreConfig,
        resolve_provider: Callable[[str], ModelProvider],
    ) -> None:
        self._pool = pool
        self._config = config
        self._resolve_provider = resolve_provider
        self._observer: BaseObserver | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._debounce: dict[str, asyncio.TimerHandle] = {}
        self._watched: dict[str, tuple[str, str]] = {}  # root_path -> (tenant_id, source_id)
        self._scheduled: set[str] = set()  # roots already handed to the observer (no double-watch)
        self._bg: set[asyncio.Task[None]] = set()
        self._safety_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Set up a watch per enabled source (fast), start the observer, and kick the initial full
        reconcile + the safety-net loop in the background so startup is not blocked by indexing."""
        self._loop = asyncio.get_running_loop()
        self._observer = Observer()
        rows = await self._enabled_sources()
        for tenant_id, source_id, root_path in rows:
            self._ensure_watch(root_path, tenant_id, source_id)
        self._observer.start()
        self._spawn(self._initial_reconcile(rows))
        self._safety_task = asyncio.create_task(self._safety_net())

    async def stop(self) -> None:
        """Cancel pending debounces + the safety net and join the observer thread (bounded)."""
        if self._safety_task is not None:
            self._safety_task.cancel()
        for handle in self._debounce.values():
            handle.cancel()
        self._debounce.clear()
        if self._observer is not None:
            self._observer.stop()
            await asyncio.to_thread(self._observer.join, 5)
            self._observer = None

    async def reconcile(self) -> None:
        """Sync every enabled source and ensure each is watched — the startup + safety-net entry
        and the recovery path (re-derives all pending work from disk vs the DB)."""
        rows = await self._enabled_sources()
        for tenant_id, source_id, root_path in rows:
            self._ensure_watch(root_path, tenant_id, source_id)
            await self._sync(tenant_id, source_id)

    # --- internals ---------------------------------------------------------------------------

    async def _enabled_sources(self) -> list[tuple[str, str, str]]:
        # Owner conn bypasses RLS -> all enabled sources across tenants (usually one, local-first).
        rows = await self._pool.fetch(
            "SELECT id, tenant_id, root_path FROM folder_sources WHERE enabled = true"
        )
        return [(str(r["tenant_id"]), str(r["id"]), r["root_path"]) for r in rows]

    def _ensure_watch(self, root_path: str, tenant_id: str, source_id: str) -> None:
        self._watched[root_path] = (tenant_id, source_id)
        if self._observer is None or self._loop is None or root_path in self._scheduled:
            return
        handler = _SourceHandler(self._loop, partial(self._on_change, root_path))
        try:
            self._observer.schedule(handler, root_path, recursive=True)
            self._scheduled.add(root_path)
        except (OSError, FileNotFoundError) as exc:  # unreadable/vanished root — safety net retries
            logger.warning("folder watch could not start for %s: %s", root_path, exc)

    def _on_change(self, root_path: str) -> None:
        """On the event loop (via call_soon_threadsafe from the observer thread): debounce."""
        if self._loop is None:
            return
        existing = self._debounce.pop(root_path, None)
        if existing is not None:
            existing.cancel()
        self._debounce[root_path] = self._loop.call_later(
            _DEBOUNCE_S, lambda: self._spawn(self._fire(root_path))
        )

    async def _fire(self, root_path: str) -> None:
        self._debounce.pop(root_path, None)
        watched = self._watched.get(root_path)
        if watched is not None:
            await self._sync(*watched)

    async def _sync(self, tenant_id: str, source_id: str) -> None:
        """Run a full sync of one source under its tenant context. Best-effort: errors are logged
        and reflected in the source/file status, never raised to the watcher loop."""
        current_security.set(SecurityContext(subject_id="folder-sync", tenant_id=tenant_id))
        querier = TenantQuerier(self._pool)
        store = PgFolderStore(querier)
        source = await store.get_source(source_id)
        if source is None or not source.enabled:
            return
        entities = PgEntityStore(querier)
        chat_provider = self._resolve_provider(self._config.model_provider)

        async def _index(text: str, document_id: str) -> None:
            await index_document_entities(
                text, document_id, store=entities, provider=chat_provider,
                model=self._config.default_model,
            )

        try:
            await sync_source(
                store,
                PgDocumentStore(querier),
                PgVectorRepository(querier),
                provider=self._resolve_provider(self._config.embed_provider),
                config=self._config,
                source=source,
                entity_indexer=_index,
                entity_store=entities,
            )
        except FolderSyncError as exc:
            logger.warning("folder sync refused for %s: %s", source_id, exc)
        except Exception as exc:  # noqa: BLE001 - best-effort; status reflects the failure
            logger.warning("folder sync error for %s: %s", source_id, exc)

    async def _initial_reconcile(self, rows: list[tuple[str, str, str]]) -> None:
        for tenant_id, source_id, _root in rows:
            await self._sync(tenant_id, source_id)

    async def _safety_net(self) -> None:
        while True:
            try:
                await asyncio.sleep(_SAFETY_NET_S)
                await self.reconcile()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the safety net must never die
                logger.warning("folder safety-net reconcile failed: %s", exc)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.ensure_future(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
