"""#290: PgAgentConfigStore round-trips and isolates by tenant under RLS (real Postgres)."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from personalai_contracts.schemas import AgentConfig, AgentGraphConfig
from personalai_storage_postgres import (
    PgAgentConfigStore,
    PgTenantStore,
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


def test_agent_config_round_trip() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            a = (await tenants.create_tenant(f"A-{uuid.uuid4()}")).id

            async with tdb.acquire(a) as conn:
                store = PgAgentConfigStore(conn)
                assert await store.get() == AgentGraphConfig()  # empty default

                saved = await store.upsert(
                    AgentGraphConfig(
                        agents=(
                            AgentConfig(name="planner", prompt="Plan tersely."),
                            AgentConfig(name="researcher", disabled_tools=("http_fetch",)),
                        )
                    )
                )
                assert saved.prompt_overrides() == {"planner": "Plan tersely."}
                assert saved.disabled_tools("researcher") == frozenset({"http_fetch"})
                assert saved.disabled_tools("planner") == frozenset()

            # Persisted across a fresh bound connection.
            async with tdb.acquire(a) as conn:
                reloaded = await PgAgentConfigStore(conn).get()
                assert reloaded.prompt_overrides() == {"planner": "Plan tersely."}
                assert reloaded.disabled_tools("researcher") == frozenset({"http_fetch"})
        finally:
            await pool.close()

    asyncio.run(_run())


def test_agent_config_is_tenant_isolated() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            a = (await tenants.create_tenant(f"A-{uuid.uuid4()}")).id
            b = (await tenants.create_tenant(f"B-{uuid.uuid4()}")).id

            async with tdb.acquire(a) as conn:
                await PgAgentConfigStore(conn).upsert(
                    AgentGraphConfig(agents=(AgentConfig(name="planner", prompt="A-plan"),))
                )
            async with tdb.acquire(b) as conn:
                # B never saved anything -> sees the empty default, NOT A's override (RLS).
                assert await PgAgentConfigStore(conn).get() == AgentGraphConfig()
            async with tdb.acquire(a) as conn:
                assert (await PgAgentConfigStore(conn).get()).prompt_overrides() == {
                    "planner": "A-plan"
                }
        finally:
            await pool.close()

    asyncio.run(_run())
