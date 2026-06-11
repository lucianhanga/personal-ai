"""Postgres connection pool and a tiny forward-only SQL migration runner (ADR-0005)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import asyncpg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Querier(Protocol):
    """The query surface the stores use. Satisfied by asyncpg Pool/Connection and by a tenant-bound
    proxy (ADR-0010, P0.5/P2) so RLS-scoped access can be dropped in without changing the stores."""

    async def execute(self, query: str, *args: Any, **kwargs: Any) -> Any: ...
    async def executemany(self, query: str, args: Any, **kwargs: Any) -> Any: ...
    async def fetch(self, query: str, *args: Any, **kwargs: Any) -> Any: ...
    async def fetchrow(self, query: str, *args: Any, **kwargs: Any) -> Any: ...


# SQL for a row's tenant: the bound tenant (app.tenant_id GUC) when set, else the default tenant.
# Lets INSERTs satisfy RLS WITH CHECK on a tenant-bound connection and still work on the raw pool
# (default tenant) where the app is not yet tenant-bound. P0.4 later drops the column default.
TENANT_ID_SQL = (
    "coalesce(current_setting('app.tenant_id', true)::uuid, "
    "'00000000-0000-0000-0000-000000000001'::uuid)"
)


async def create_pool(database_url: str) -> asyncpg.Pool:
    """Create an asyncpg connection pool for ``database_url``."""
    return await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=5)


async def apply_migrations(pool: asyncpg.Pool, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply any unapplied ``*.sql`` migrations in order; return the versions applied."""
    applied: list[str] = []
    async with pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
        for path in sorted(migrations_dir.glob("*.sql")):
            if path.name in done:
                continue
            sql = path.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute("INSERT INTO schema_migrations(version) VALUES($1)", path.name)
            applied.append(path.name)
    return applied
