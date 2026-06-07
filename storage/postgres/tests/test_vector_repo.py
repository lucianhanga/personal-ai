"""PgVectorRepository against a REAL Postgres + pgvector.

Skipped when no database is reachable (run `make db` locally; CI provides a service container).
"""

from __future__ import annotations

import asyncio
import os

import pytest

from personalai_contracts.ports import VectorRecord, VectorRepository
from personalai_storage_postgres import (
    VECTOR_DIM,
    PgVectorRepository,
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


def test_apply_migrations_runs_then_is_idempotent() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            # Reset migration state so the apply path runs deterministically (volume may persist).
            await pool.execute("DROP TABLE IF EXISTS vectors")
            await pool.execute("DROP TABLE IF EXISTS schema_migrations")
            applied = await apply_migrations(pool)
            assert "0001_init.sql" in applied
            assert await apply_migrations(pool) == []  # nothing left to apply
        finally:
            await pool.close()

    asyncio.run(_run())


def _vec(*lead: float) -> list[float]:
    """A VECTOR_DIM-long vector with the given leading values, zero-padded."""
    values = list(lead)
    return values + [0.0] * (VECTOR_DIM - len(values))


def test_upsert_query_delete_roundtrip() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            await pool.execute("TRUNCATE vectors")
            repo = PgVectorRepository(pool)
            assert isinstance(repo, VectorRepository)

            await repo.upsert(
                [
                    VectorRecord(id="a", vector=_vec(1.0, 0.0), metadata={"t": "a"}),
                    VectorRecord(id="b", vector=_vec(0.0, 1.0), metadata={"t": "b"}),
                ]
            )
            matches = await repo.query(_vec(1.0, 0.0), top_k=2)
            assert matches[0].id == "a"  # nearest by cosine
            assert matches[0].metadata["t"] == "a"
            assert matches[0].score >= matches[1].score

            await repo.delete(["a"])
            remaining = [m.id for m in await repo.query(_vec(1.0, 0.0), top_k=5)]
            assert "a" not in remaining
            assert "b" in remaining
        finally:
            await pool.close()

    asyncio.run(_run())


def test_upsert_is_idempotent_on_conflict() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            await pool.execute("TRUNCATE vectors")
            repo = PgVectorRepository(pool)
            await repo.upsert([VectorRecord(id="x", vector=_vec(1.0), metadata={"v": 1})])
            await repo.upsert([VectorRecord(id="x", vector=_vec(1.0), metadata={"v": 2})])
            matches = await repo.query(_vec(1.0), top_k=5)
            assert len([m for m in matches if m.id == "x"]) == 1
            assert next(m for m in matches if m.id == "x").metadata["v"] == 2
        finally:
            await pool.close()

    asyncio.run(_run())
