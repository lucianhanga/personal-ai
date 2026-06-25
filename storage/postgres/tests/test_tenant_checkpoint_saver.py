"""M8.1a: the tenant-scoped LangGraph checkpointer against a REAL Postgres (skipped when no DB).

Proves (1) durable interrupt/resume across fresh saver instances, (2) the headline cross-tenant
isolation gate — a saver bound to tenant B cannot read or resume tenant A's thread (RLS), and
(3) the saver's put/get/list surface directly.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import create_checkpoint, empty_checkpoint
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from personalai_storage_postgres import (
    PgTenantStore,
    TenantCheckpointSaver,
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


class _S(TypedDict, total=False):
    value: int
    approved: str


def _gate_graph() -> StateGraph[_S, Any, _S, _S]:
    """A one-node graph that suspends on a human gate via interrupt()."""

    def gate(state: _S) -> _S:
        decision = interrupt("approve?")  # suspends; resumes with Command(resume=...)
        return {"approved": decision, "value": state.get("value", 0) + 1}

    builder = StateGraph(_S)
    builder.add_node("gate", gate)
    builder.add_edge(START, "gate")
    builder.add_edge("gate", END)
    return builder


def test_durable_interrupt_resume_across_saver_instances() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tdb = TenantDb(pool)
            tenant = (await PgTenantStore(pool).create_tenant("A")).id
            run_id = str(uuid.uuid4())
            config: RunnableConfig = {"configurable": {"thread_id": run_id}}

            # First pass: runs until the human gate, then suspends (checkpointed to Postgres).
            saver1 = TenantCheckpointSaver(tdb, tenant)
            app1 = _gate_graph().compile(checkpointer=saver1)
            result = await app1.ainvoke({"value": 1}, config)
            assert "__interrupt__" in result  # suspended at the gate

            # Resume with a FRESH saver instance -> state must come from Postgres, not memory.
            saver2 = TenantCheckpointSaver(tdb, tenant)
            app2 = _gate_graph().compile(checkpointer=saver2)
            final = await app2.ainvoke(Command(resume="yes"), config)
            assert final["approved"] == "yes"
            assert final["value"] == 2
        finally:
            await pool.close()

    asyncio.run(_run())


def test_cross_tenant_cannot_read_or_resume() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tdb = TenantDb(pool)
            tenants = PgTenantStore(pool)
            a = (await tenants.create_tenant("A")).id
            b = (await tenants.create_tenant("B")).id
            run_id = str(uuid.uuid4())
            config: RunnableConfig = {"configurable": {"thread_id": run_id}}

            # Tenant A suspends a run at the gate.
            app_a = _gate_graph().compile(checkpointer=TenantCheckpointSaver(tdb, a))
            await app_a.ainvoke({"value": 1}, config)

            # Tenant B, even with the exact run_id, sees nothing (RLS): cannot read the checkpoint.
            saver_b = TenantCheckpointSaver(tdb, b)
            assert await saver_b.aget_tuple(config) is None

            # And a resume attempt as B does not run A's gated turn (no state to resume from).
            app_b = _gate_graph().compile(checkpointer=saver_b)
            res_b = await app_b.ainvoke(Command(resume="hijack"), config)
            assert res_b.get("approved") != "hijack"

            # A can still read + resume its own run.
            assert await TenantCheckpointSaver(tdb, a).aget_tuple(config) is not None
        finally:
            await pool.close()

    asyncio.run(_run())


def test_adelete_thread_clears_a_gated_run() -> None:
    """#412: adelete_thread removes a suspended run's durable checkpoint so it is no longer
    resumable (a subsequent aget_tuple -> None, the /resume 404 rule), and is idempotent."""

    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tdb = TenantDb(pool)
            tenant = (await PgTenantStore(pool).create_tenant("A")).id
            run_id = str(uuid.uuid4())
            config: RunnableConfig = {"configurable": {"thread_id": run_id}}

            # Suspend a run at the gate so a checkpoint (and pending writes) exist.
            saver = TenantCheckpointSaver(tdb, tenant)
            app = _gate_graph().compile(checkpointer=saver)
            assert "__interrupt__" in await app.ainvoke({"value": 1}, config)
            assert await saver.aget_tuple(config) is not None

            # Cancel: delete the thread -> no checkpoint remains, so it can't be resumed.
            await saver.adelete_thread(run_id)
            assert await saver.aget_tuple(config) is None

            # Idempotent: deleting an already-cleared thread is a no-op (safe double-click Stop).
            await saver.adelete_thread(run_id)
            assert await saver.aget_tuple(config) is None
        finally:
            await pool.close()

    asyncio.run(_run())


def test_adelete_thread_is_tenant_scoped() -> None:
    """#412: adelete_thread runs under RLS — tenant B deleting A's run_id removes nothing; A's
    checkpoint survives and stays resumable."""

    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tdb = TenantDb(pool)
            tenants = PgTenantStore(pool)
            a = (await tenants.create_tenant("A")).id
            b = (await tenants.create_tenant("B")).id
            run_id = str(uuid.uuid4())
            config: RunnableConfig = {"configurable": {"thread_id": run_id}}

            app_a = _gate_graph().compile(checkpointer=TenantCheckpointSaver(tdb, a))
            await app_a.ainvoke({"value": 1}, config)

            # B attempts to delete A's run by id -> RLS scopes the delete to B, so A's rows remain.
            await TenantCheckpointSaver(tdb, b).adelete_thread(run_id)
            assert await TenantCheckpointSaver(tdb, a).aget_tuple(config) is not None
        finally:
            await pool.close()

    asyncio.run(_run())


def test_put_get_list_directly() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tdb = TenantDb(pool)
            tenant = (await PgTenantStore(pool).create_tenant("A")).id
            saver = TenantCheckpointSaver(tdb, tenant)
            thread_id = str(uuid.uuid4())
            base: RunnableConfig = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

            # Two checkpoints in a parent->child chain, with a pending write on the child.
            cp1 = empty_checkpoint()
            cfg1 = await saver.aput(base, cp1, {"source": "input", "step": -1}, {})
            cp2 = create_checkpoint(cp1, {}, 1)
            cfg2 = await saver.aput(cfg1, cp2, {"source": "loop", "step": 0}, {})
            await saver.aput_writes(cfg2, [("messages", "hi"), ("__interrupt__", "x")], "task-1")

            # Latest (no id) -> cp2, with parent + the pending writes.
            latest = await saver.aget_tuple(base)
            assert latest is not None
            assert latest.parent_config is not None
            assert latest.pending_writes is not None
            assert latest.config["configurable"]["checkpoint_id"] == cp2["id"]
            assert latest.parent_config["configurable"]["checkpoint_id"] == cp1["id"]
            assert ("task-1", "messages", "hi") in latest.pending_writes

            # By explicit id -> cp1 (the root, no parent).
            by_id = await saver.aget_tuple(cfg1)
            assert by_id is not None and by_id.parent_config is None

            # list returns newest-first; before+limit narrow it.
            ids = [t.config["configurable"]["checkpoint_id"] async for t in saver.alist(base)]
            assert ids == [cp2["id"], cp1["id"]]
            before = [
                t.config["configurable"]["checkpoint_id"]
                async for t in saver.alist(base, before=cfg2)
            ]
            assert before == [cp1["id"]]
            limited = [c async for c in saver.alist(base, limit=1)]
            assert len(limited) == 1
        finally:
            await pool.close()

    asyncio.run(_run())
