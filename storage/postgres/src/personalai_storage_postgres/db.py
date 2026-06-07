"""Postgres connection pool and a tiny forward-only SQL migration runner (ADR-0005)."""

from __future__ import annotations

from pathlib import Path

import asyncpg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


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
