"""B2: tenant-scoped uniqueness — the same vector/document id can exist for two tenants."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from personalai_contracts.ports.storage import VectorRecord
from personalai_storage_postgres import (
    VECTOR_DIM,
    PgTenantStore,
    PgVectorRepository,
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


def test_same_vector_id_for_two_tenants_does_not_conflict() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            a = (await tenants.create_tenant("A")).id
            b = (await tenants.create_tenant("B")).id
            dup_id = f"dup-{uuid.uuid4()}"
            rec = VectorRecord(id=dup_id, vector=[0.0] * VECTOR_DIM, metadata={"t": "x"})

            async with tdb.acquire(a) as conn:
                await PgVectorRepository(conn).upsert([rec])
            # Same id under tenant B must NOT raise a cross-tenant ON CONFLICT error.
            async with tdb.acquire(b) as conn:
                await PgVectorRepository(conn).upsert([rec])

            # Both rows exist (one per tenant) — verified via the raw pool (superuser bypasses RLS).
            count = await pool.fetchval("SELECT count(*) FROM vectors WHERE id = $1", dup_id)
            assert count == 2
        finally:
            await pool.close()

    asyncio.run(_run())
