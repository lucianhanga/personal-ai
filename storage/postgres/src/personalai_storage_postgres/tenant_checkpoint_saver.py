"""Tenant-scoped LangGraph checkpoint saver (M8.1a, ADR-0012 / ADR-0010).

LangGraph's checkpoint is the durable interrupt/resume state. This saver persists it to Postgres
**tenant-scoped under RLS**: an instance is *bound to one tenant* and routes every read/write
through :class:`TenantDb` (``SET LOCAL ROLE personalai_app`` + ``app.tenant_id`` per transaction),
so a saver bound to tenant B can never see or resume tenant A's threads — the isolation is enforced
by the database (migration 0014), not just application code (defense-in-depth, fail-closed).

It stores the whole checkpoint inline (serialized via LangGraph's serializer) rather than
externalizing channel blobs: simpler, and our turns are small. ``thread_id`` is the run id.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)

from personalai_storage_postgres.tenant_db import TenantDb


class TenantCheckpointSaver(BaseCheckpointSaver[str]):
    """A LangGraph checkpointer bound to a single tenant; every op goes through ``TenantDb`` so RLS
    isolates tenants at the database layer."""

    def __init__(self, tenant_db: TenantDb, tenant_id: str, *, serde: Any = None) -> None:
        super().__init__(serde=serde)
        self._db = tenant_db
        self._tenant = tenant_id

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        cfg = config["configurable"]
        thread_id, ns = cfg["thread_id"], cfg.get("checkpoint_ns", "")
        cp_type, cp_blob = self.serde.dumps_typed(checkpoint)
        md_type, md_blob = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        async with self._db.acquire(self._tenant) as conn:
            await conn.execute(
                "INSERT INTO agent_checkpoints(tenant_id, thread_id, checkpoint_ns, checkpoint_id, "
                "parent_checkpoint_id, type, checkpoint, metadata_type, metadata) "
                "VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9) "
                "ON CONFLICT (tenant_id, thread_id, checkpoint_ns, checkpoint_id) DO UPDATE SET "
                "parent_checkpoint_id=excluded.parent_checkpoint_id, type=excluded.type, "
                "checkpoint=excluded.checkpoint, metadata_type=excluded.metadata_type, "
                "metadata=excluded.metadata",
                self._tenant,
                thread_id,
                ns,
                checkpoint["id"],
                cfg.get("checkpoint_id"),
                cp_type,
                cp_blob,
                md_type,
                md_blob,
            )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        cfg = config["configurable"]
        thread_id, ns = cfg["thread_id"], cfg.get("checkpoint_ns", "")
        checkpoint_id = cfg["checkpoint_id"]
        async with self._db.acquire(self._tenant) as conn:
            for idx, (channel, value) in enumerate(writes):
                w_type, w_blob = self.serde.dumps_typed(value)
                await conn.execute(
                    "INSERT INTO agent_checkpoint_writes(tenant_id, thread_id, checkpoint_ns, "
                    "checkpoint_id, task_id, idx, channel, type, blob) "
                    "VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9) "
                    "ON CONFLICT (tenant_id, thread_id, checkpoint_ns, checkpoint_id, task_id, "
                    "idx) DO UPDATE SET channel=excluded.channel, type=excluded.type, "
                    "blob=excluded.blob",
                    self._tenant,
                    thread_id,
                    ns,
                    checkpoint_id,
                    task_id,
                    WRITES_IDX_MAP.get(channel, idx),
                    channel,
                    w_type,
                    w_blob,
                )

    async def adelete_thread(self, thread_id: str) -> None:
        """Delete all durable checkpoint state for ``thread_id`` (the run id), tenant-scoped (#412).

        Used by ``POST /chat/{run_id}/cancel`` so a cancelled gated run is not left resumable: a
        subsequent ``/resume`` finds no checkpoint and 404s naturally (matching the existing
        ``aget_tuple is None -> 404`` rule). Both deletes run in ONE ``TenantDb`` unit of work, so
        the checkpoint rows and their writes commit/roll back together; RLS (migration 0014) scopes
        the delete to the bound tenant (belt-and-suspenders to the explicit ``thread_id``).
        Idempotent: deleting an already-finished/already-cancelled thread is a no-op (0 rows), so a
        double-click Stop is safe.
        """
        async with self._db.acquire(self._tenant) as conn:
            await conn.execute("DELETE FROM agent_checkpoint_writes WHERE thread_id=$1", thread_id)
            await conn.execute("DELETE FROM agent_checkpoints WHERE thread_id=$1", thread_id)

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        cfg = config["configurable"]
        thread_id, ns = cfg["thread_id"], cfg.get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)
        async with self._db.acquire(self._tenant) as conn:
            if checkpoint_id:
                row = await conn.fetchrow(
                    "SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata_type, "
                    "metadata FROM agent_checkpoints WHERE thread_id=$1 AND checkpoint_ns=$2 "
                    "AND checkpoint_id=$3",
                    thread_id,
                    ns,
                    checkpoint_id,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata_type, "
                    "metadata FROM agent_checkpoints WHERE thread_id=$1 AND checkpoint_ns=$2 "
                    "ORDER BY checkpoint_id DESC LIMIT 1",
                    thread_id,
                    ns,
                )
            if row is None:
                return None
            writes = await conn.fetch(
                "SELECT task_id, channel, type, blob FROM agent_checkpoint_writes "
                "WHERE thread_id=$1 AND checkpoint_ns=$2 AND checkpoint_id=$3 "
                "ORDER BY task_id, idx",
                thread_id,
                ns,
                row["checkpoint_id"],
            )
        return self._to_tuple(thread_id, ns, row, writes)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        thread_id = config["configurable"]["thread_id"] if config else ""
        ns = config["configurable"].get("checkpoint_ns", "") if config else ""
        before_id = get_checkpoint_id(before) if before else None
        sql = (
            "SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata_type, metadata "
            "FROM agent_checkpoints WHERE thread_id=$1 AND checkpoint_ns=$2"
        )
        args: list[Any] = [thread_id, ns]
        if before_id:
            args.append(before_id)
            sql += f" AND checkpoint_id < ${len(args)}"
        sql += " ORDER BY checkpoint_id DESC"
        if limit is not None:
            args.append(limit)
            sql += f" LIMIT ${len(args)}"
        async with self._db.acquire(self._tenant) as conn:
            rows = await conn.fetch(sql, *args)
            for row in rows:
                writes = await conn.fetch(
                    "SELECT task_id, channel, type, blob FROM agent_checkpoint_writes "
                    "WHERE thread_id=$1 AND checkpoint_ns=$2 AND checkpoint_id=$3 "
                    "ORDER BY task_id, idx",
                    thread_id,
                    ns,
                    row["checkpoint_id"],
                )
                yield self._to_tuple(thread_id, ns, row, writes)

    def _to_tuple(self, thread_id: str, ns: str, row: Any, writes: Any) -> CheckpointTuple:
        parent = row["parent_checkpoint_id"]
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": ns,
                    "checkpoint_id": row["checkpoint_id"],
                }
            },
            checkpoint=self.serde.loads_typed((row["type"], row["checkpoint"])),
            metadata=self.serde.loads_typed((row["metadata_type"], row["metadata"])),
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": ns,
                        "checkpoint_id": parent,
                    }
                }
                if parent
                else None
            ),
            pending_writes=[
                (w["task_id"], w["channel"], self.serde.loads_typed((w["type"], w["blob"])))
                for w in writes
            ],
        )
