"""P0.2: every domain table is tenant-scoped and new rows default to the default tenant.

Verifies the additive tenant_id columns against a REAL Postgres (skipped when no DB).
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from personalai_storage_postgres import (
    DEFAULT_TENANT_ID,
    PgConversationStore,
    apply_migrations,
    create_pool,
)

DB_URL = os.environ.get(
    "PERSONALAI_DATABASE_URL", "postgresql://personalai@127.0.0.1:5432/personalai"
)

_DOMAIN_TABLES = ["conversations", "messages", "documents", "vectors", "memories"]


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


def test_domain_tables_have_tenant_id() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            for table in _DOMAIN_TABLES:
                col = await pool.fetchrow(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = $1 AND column_name = 'tenant_id'",
                    table,
                )
                assert col is not None, f"{table} missing tenant_id"
                assert col["is_nullable"] == "NO", f"{table}.tenant_id must be NOT NULL"
        finally:
            await pool.close()

    asyncio.run(_run())


def test_new_row_defaults_to_default_tenant() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            store = PgConversationStore(pool)
            conv = await store.create(id=str(uuid.uuid4()), title="t")
            tid = await pool.fetchval("SELECT tenant_id FROM conversations WHERE id = $1", conv.id)
            assert str(tid) == DEFAULT_TENANT_ID  # default applied until repos set it (P0.5)
        finally:
            await pool.close()

    asyncio.run(_run())
