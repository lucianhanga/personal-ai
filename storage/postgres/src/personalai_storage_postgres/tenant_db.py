"""Tenant-bound database access (ADR-0010, P0.3).

``TenantDb.acquire(tenant_id)`` hands out a connection bound to one tenant for the duration of a
transaction: it drops to the NOBYPASSRLS ``personalai_app`` role and sets ``app.tenant_id`` **per
transaction** (never SESSION — an asyncpg pool reuses connections, and a leaked SESSION setting
would cross tenants). Postgres RLS (migration 0009) then restricts every row to that tenant. A
repository only ever receives this bound connection, so a query without a tenant is structurally
impossible — and even if one slipped through, RLS denies it (fail-closed, two layers).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

# The NOBYPASSRLS role the app assumes per transaction so RLS is enforced even when the pool
# connects as a superuser/owner. Constant (never interpolated from input).
APP_ROLE = "personalai_app"


class TenantDb:
    """Hands out tenant-bound connections so RLS is always enforced."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @asynccontextmanager
    async def acquire(self, tenant_id: str) -> AsyncIterator[asyncpg.Connection]:
        """Yield a connection bound to ``tenant_id`` for one transaction (RLS active)."""
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(f"SET LOCAL ROLE {APP_ROLE}")
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))
            yield conn
