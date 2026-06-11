"""P0.3: Row-Level Security tenant isolation via TenantDb (the headline cross-tenant tests).

Proven directly at the RLS layer against a REAL Postgres (skipped when no DB).
"""

from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import pytest

from personalai_storage_postgres import PgTenantStore, TenantDb, apply_migrations, create_pool

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


def test_rls_isolates_two_tenants() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            a = (await tenants.create_tenant("A")).id
            b = (await tenants.create_tenant("B")).id
            id_a, id_b = f"a-{uuid.uuid4()}", f"b-{uuid.uuid4()}"

            # Each tenant inserts a conversation through its own bound connection.
            async with tdb.acquire(a) as conn:
                await conn.execute(
                    "INSERT INTO conversations(id, title, tenant_id) VALUES($1, 'A conv', $2)",
                    id_a,
                    a,
                )
            async with tdb.acquire(b) as conn:
                await conn.execute(
                    "INSERT INTO conversations(id, title, tenant_id) VALUES($1, 'B conv', $2)",
                    id_b,
                    b,
                )

            # Tenant A sees only its own row; B's row is invisible at the DB layer.
            async with tdb.acquire(a) as conn:
                ids = {r["id"] for r in await conn.fetch("SELECT id FROM conversations")}
                assert id_a in ids and id_b not in ids
                # A cannot read B's row even by id, and cannot delete it.
                assert (
                    await conn.fetchval("SELECT count(*) FROM conversations WHERE id=$1", id_b) == 0
                )
                await conn.execute("DELETE FROM conversations WHERE id=$1", id_b)  # affects 0 rows
            async with tdb.acquire(b) as conn:  # B's row survived A's delete attempt
                assert (
                    await conn.fetchval("SELECT count(*) FROM conversations WHERE id=$1", id_b) == 1
                )
        finally:
            await pool.close()

    asyncio.run(_run())


def test_rls_blocks_cross_tenant_insert() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            tdb = TenantDb(pool)
            a = (await tenants.create_tenant("A")).id
            b = (await tenants.create_tenant("B")).id
            # Bound to A, try to write a row stamped for B -> WITH CHECK rejects it.
            async with tdb.acquire(a) as conn:
                with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
                    await conn.execute(
                        "INSERT INTO conversations(id, title, tenant_id) VALUES($1,'x',$2)",
                        f"x-{uuid.uuid4()}",
                        b,
                    )
        finally:
            await pool.close()

    asyncio.run(_run())
