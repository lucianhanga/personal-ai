"""#289: PgSettingsStore round-trips per-tenant and isolates by tenant under RLS (real Postgres)."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from personalai_contracts.schemas import TenantSettings
from personalai_storage_postgres import (
    PgSettingsStore,
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


def test_settings_round_trip_and_partial_inherit() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            a = (await tenants.create_tenant(f"A-{uuid.uuid4()}")).id

            async with tdb.acquire(a) as conn:
                store = PgSettingsStore(conn)
                # No row yet -> all-inherit (all None).
                assert await store.get() == TenantSettings()

                saved = await store.upsert(
                    TenantSettings(
                        default_model="qwen3:14b",
                        agent_graph_enabled=True,
                        agent_max_iterations=12,
                        grounding_enabled=False,
                        egress_enabled=True,
                        allowed_egress_hosts=("api.example.com", "files.example.org"),
                        transcribe_enabled=True,
                        transcribe_provider="local",
                        transcribe_base_url="http://127.0.0.1:8000/v1",
                        transcribe_model="whisper-1",
                        transcribe_language="ro",
                        tts_enabled=True,
                    )
                )
                assert saved.default_model == "qwen3:14b"
                assert saved.agent_graph_enabled is True
                assert saved.agent_max_iterations == 12
                assert saved.grounding_enabled is False
                # The text[] allowlist round-trips back as a tuple.
                assert saved.egress_enabled is True
                assert saved.allowed_egress_hosts == ("api.example.com", "files.example.org")
                # Voice (speech-to-text) settings round-trip (#298).
                assert saved.transcribe_enabled is True
                assert saved.transcribe_provider == "local"
                assert saved.transcribe_base_url == "http://127.0.0.1:8000/v1"
                assert saved.transcribe_model == "whisper-1"
                assert saved.transcribe_language == "ro"
                assert saved.tts_enabled is True
                # Unset fields stay None (inherit the deployment default).
                assert saved.ollama_host is None
                assert saved.memory_enabled is None

            # Persisted across a fresh bound connection.
            async with tdb.acquire(a) as conn:
                reloaded = await PgSettingsStore(conn).get()
                assert reloaded.default_model == "qwen3:14b"

            # Overwrite restores omitted fields to NULL (default).
            async with tdb.acquire(a) as conn:
                store = PgSettingsStore(conn)
                await store.upsert(TenantSettings(default_model="gemma3:27b"))
                latest = await store.get()
                assert latest.default_model == "gemma3:27b"
                assert latest.agent_graph_enabled is None  # cleared on overwrite
        finally:
            await pool.close()

    asyncio.run(_run())


def test_settings_are_tenant_isolated() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            a = (await tenants.create_tenant(f"A-{uuid.uuid4()}")).id
            b = (await tenants.create_tenant(f"B-{uuid.uuid4()}")).id

            async with tdb.acquire(a) as conn:
                await PgSettingsStore(conn).upsert(TenantSettings(default_model="model-a"))
            async with tdb.acquire(b) as conn:
                await PgSettingsStore(conn).upsert(TenantSettings(default_model="model-b"))

            # Each tenant sees ONLY its own row (RLS) -- B's settings are invisible to A.
            async with tdb.acquire(a) as conn:
                assert (await PgSettingsStore(conn).get()).default_model == "model-a"
            async with tdb.acquire(b) as conn:
                assert (await PgSettingsStore(conn).get()).default_model == "model-b"
        finally:
            await pool.close()

    asyncio.run(_run())
