"""Postgres connection pool and a tiny forward-only SQL migration runner (ADR-0005)."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Protocol

import asyncpg

from personalai_contracts.ports.storage import Scope

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def scope_predicate(scope: Scope, *, next_param: int) -> tuple[str, list[Any]]:
    """Build the scope ``WHERE`` fragment + its bound params for ``vectors``/``documents`` (#420).

    Scope is an *additional* app-layer filter, orthogonal to tenant RLS. ``next_param`` is the next
    free asyncpg placeholder index ($N); returns ``(sql_fragment, params)`` where any scope value is
    bound (never string-interpolated). Global (NULL/NULL) needs no params -- its predicate is the
    constant ``conversation_id IS NULL AND project_id IS NULL``, the anti-bleed guard that keeps
    conversation/project rows out of a global query.
    """
    if scope.is_global:
        return "conversation_id IS NULL AND project_id IS NULL", []
    if scope.conversation_id is not None:
        return f"conversation_id = ${next_param} AND project_id IS NULL", [scope.conversation_id]
    return f"project_id = ${next_param} AND conversation_id IS NULL", [scope.project_id]


def union_scope_predicate(conversation_id: str, *, next_param: int) -> tuple[str, list[Any]]:
    """Build the **union** scope ``WHERE`` fragment for "global OR this conversation" (#420 PR4).

    Tier-2 retrieval must search the UNION of the global corpus AND the active conversation's
    ephemeral attachments, so an attached large doc and the Settings -> Documents corpus are both
    visible to one question. Returns ``(sql_fragment, [conversation_id])`` where the predicate is::

        ((conversation_id IS NULL AND project_id IS NULL)
         OR (conversation_id = $N AND project_id IS NULL))

    Anti-bleed holds because the only non-global rows this can match are rows whose
    ``conversation_id`` equals the bound value: another conversation's rows (different id) and
    project rows (``conversation_id IS NULL`` but ``project_id`` set, excluded by the global arm's
    ``project_id IS NULL``) never surface. The conversation id is bound, never interpolated. Tenant
    RLS is unchanged and orthogonal (enforced on the connection).
    """
    return (
        f"((conversation_id IS NULL AND project_id IS NULL) "
        f"OR (conversation_id = ${next_param} AND project_id IS NULL))",
        [conversation_id],
    )


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


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Per-connection setup. Enable pgvector iterative index scans (0.8+): under RLS every ANN
    query is a *filtered* search, and a plain HNSW scan can return fewer than k rows (or none) for
    a small tenant once tables are shared — iterative scans re-probe until k tenant rows are found.
    Best-effort: older pgvector lacks this GUC."""
    with contextlib.suppress(asyncpg.PostgresError):  # older pgvector (< 0.8) lacks this GUC
        await conn.execute("SET hnsw.iterative_scan = relaxed_order")


async def create_pool(database_url: str, *, max_size: int = 20) -> asyncpg.Pool:
    """Create an asyncpg connection pool for ``database_url`` (``max_size`` from CoreConfig)."""
    return await asyncpg.create_pool(
        dsn=database_url, min_size=1, max_size=max_size, init=_init_connection
    )


async def apply_migrations(pool: asyncpg.Pool, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply any unapplied ``*.sql`` migrations in order; return the versions applied."""
    applied: list[str] = []
    lock_key = "SELECT {fn}(hashtext('personalai_migrations'))"
    async with pool.acquire() as conn:
        # Serialize migrations across concurrent boots (e.g. several backend instances starting at
        # once): a session-level advisory lock so exactly one runner applies migrations; the others
        # block here, then find everything applied. Unlocked in finally so it doesn't leak on the
        # pooled connection.
        await conn.execute(lock_key.format(fn="pg_advisory_lock"))
        try:
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
                    await conn.execute(
                        "INSERT INTO schema_migrations(version) VALUES($1)", path.name
                    )
                applied.append(path.name)
        finally:
            await conn.execute(lock_key.format(fn="pg_advisory_unlock"))
    return applied
