"""Per-request tenant-bound query proxy (ADR-0010, P2).

Wraps the connection pool and runs every store query on a connection bound to the current request's
tenant: ``SET LOCAL ROLE personalai_app`` drops the superuser RLS bypass and ``set_config`` binds
``app.tenant_id`` for the transaction (pool-safe — never SESSION). The stores accept this in place
of the raw pool (it satisfies the ``Querier`` protocol), so conversations/messages/documents/
vectors/memory become tenant-isolated with no endpoint changes. Fail-closed: a query with no
SecurityContext in scope raises.
"""

from __future__ import annotations

from typing import Any

import asyncpg

from personalai_core.security import current_security

APP_ROLE = "personalai_app"


class TenantContextError(RuntimeError):
    """A tenant-scoped query ran with no SecurityContext in scope (fail-closed)."""


class TenantQuerier:
    """A ``Querier`` that binds each query to ``current_security``'s tenant via RLS."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    def _tenant_id(self) -> str:
        ctx = current_security.get()
        if ctx is None:
            raise TenantContextError("no security context for a tenant-scoped query")
        return ctx.tenant_id

    async def _bind(self, conn: asyncpg.Connection) -> None:
        await conn.execute(f"SET LOCAL ROLE {APP_ROLE}")
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", self._tenant_id())

    async def execute(self, query: str, *args: Any, **kwargs: Any) -> Any:
        self._tenant_id()  # fail-closed before acquiring a connection
        async with self._pool.acquire() as conn, conn.transaction():
            await self._bind(conn)
            return await conn.execute(query, *args, **kwargs)

    async def executemany(self, query: str, args: Any, **kwargs: Any) -> Any:
        self._tenant_id()
        async with self._pool.acquire() as conn, conn.transaction():
            await self._bind(conn)
            return await conn.executemany(query, args, **kwargs)

    async def fetch(self, query: str, *args: Any, **kwargs: Any) -> Any:
        self._tenant_id()
        async with self._pool.acquire() as conn, conn.transaction():
            await self._bind(conn)
            return await conn.fetch(query, *args, **kwargs)

    async def fetchrow(self, query: str, *args: Any, **kwargs: Any) -> Any:
        self._tenant_id()
        async with self._pool.acquire() as conn, conn.transaction():
            await self._bind(conn)
            return await conn.fetchrow(query, *args, **kwargs)
