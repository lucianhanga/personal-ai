"""PgSessionStore: create/get/expiry/revoke against a REAL Postgres (skipped when no DB)."""

from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import pytest

from personalai_storage_postgres import (
    PgSessionStore,
    PgTenantStore,
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


async def _subject_in_tenant(pool: asyncpg.Pool) -> tuple[str, str]:
    store = PgTenantStore(pool)
    tenant = await store.create_tenant("S")
    subject = await store.create_subject(email=f"{uuid.uuid4().hex[:8]}@example.com")
    return tenant.id, subject.id


def test_create_get_and_revoke() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenant_id, subject_id = await _subject_in_tenant(pool)
            store = PgSessionStore(pool)
            token, session = await store.create(tenant_id, subject_id)
            assert session.tenant_id == tenant_id and session.subject_id == subject_id
            got = await store.get(token)
            assert got is not None and got.id == session.id
            assert await store.get("not-a-real-token") is None  # unknown token
            await store.revoke(session.id)
            assert await store.get(token) is None  # revoked
        finally:
            await pool.close()

    asyncio.run(_run())


def test_idle_and_absolute_expiry() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenant_id, subject_id = await _subject_in_tenant(pool)
            # idle window already elapsed -> get returns None
            idle_store = PgSessionStore(pool, idle_seconds=-10)
            token, _ = await idle_store.create(tenant_id, subject_id)
            assert await idle_store.get(token) is None
            # absolute cap already elapsed -> get returns None
            abs_store = PgSessionStore(pool, absolute_seconds=-10)
            token2, _ = await abs_store.create(tenant_id, subject_id)
            assert await abs_store.get(token2) is None
        finally:
            await pool.close()

    asyncio.run(_run())


def test_revoke_all_for_subject() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenant_id, subject_id = await _subject_in_tenant(pool)
            store = PgSessionStore(pool)
            t1, _ = await store.create(tenant_id, subject_id)
            t2, _ = await store.create(tenant_id, subject_id)
            await store.revoke_all_for_subject(subject_id)
            assert await store.get(t1) is None and await store.get(t2) is None
        finally:
            await pool.close()

    asyncio.run(_run())
