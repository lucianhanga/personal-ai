"""B1: the pool enables pgvector iterative scans so ANN top-k survives RLS filtering."""

from __future__ import annotations

import asyncio
import os

import pytest

from personalai_storage_postgres import apply_migrations, create_pool

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


def test_pool_enables_hnsw_iterative_scan() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            value = await pool.fetchval("SELECT current_setting('hnsw.iterative_scan', true)")
            # pgvector >= 0.8 (CI + local use pgvector/pgvector:pg17 -> 0.8+).
            assert value == "relaxed_order"
        finally:
            await pool.close()

    asyncio.run(_run())


def test_apply_migrations_twice_does_not_deadlock() -> None:
    # The advisory lock must be released (not leaked on the pooled connection): a second run on the
    # same pool must complete (and find everything already applied) rather than block forever.
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            second = await asyncio.wait_for(apply_migrations(pool), timeout=10)
            assert second == []  # all already applied; lock was released
        finally:
            await pool.close()

    asyncio.run(_run())
