"""PgTenantStore against a REAL Postgres (skipped when no DB).

Exercises tenancy with TWO tenants from the start — the only way to prove multi-tenant behavior.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from personalai_storage_postgres import (
    DEFAULT_TENANT_ID,
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


def test_default_tenant_is_seeded() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            store = PgTenantStore(pool)
            default = await store.get_tenant(DEFAULT_TENANT_ID)
            assert default is not None and default.name == "default"
            assert await store.get_tenant(str(uuid.uuid4())) is None  # unknown tenant
        finally:
            await pool.close()

    asyncio.run(_run())


def test_two_tenants_subjects_and_memberships() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            store = PgTenantStore(pool)
            tenant_a = await store.create_tenant("Acme")
            tenant_b = await store.create_tenant("Globex")
            assert tenant_a.id != tenant_b.id

            uniq = uuid.uuid4().hex[:8]
            alice = await store.create_subject(
                email=f"Alice+{uniq}@EXAMPLE.com", display_name="Alice"
            )
            assert alice.email == f"alice+{uniq}@example.com"  # normalized lower-case
            # lookup is case-insensitive via the same normalization
            found = await store.get_subject_by_email(f"ALICE+{uniq}@example.com")
            assert found is not None and found.id == alice.id

            # the same subject can belong to two tenants (org-ready); roles round-trip + upsert
            await store.add_membership(tenant_a.id, alice.id, role="admin")
            await store.add_membership(tenant_b.id, alice.id)  # default 'member'
            await store.add_membership(tenant_a.id, alice.id, role="owner")  # upsert role
            memberships = dict(await store.memberships_for_subject(alice.id))
            assert memberships == {tenant_a.id: "owner", tenant_b.id: "member"}
        finally:
            await pool.close()

    asyncio.run(_run())


def test_subject_email_is_unique() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            store = PgTenantStore(pool)
            email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
            await store.create_subject(email=email)
            with pytest.raises(Exception):  # noqa: B017 - asyncpg UniqueViolationError
                await store.create_subject(email=email)
            # a service principal with no email is allowed (multiple NULLs are fine)
            assert (await store.create_subject()).email is None
        finally:
            await pool.close()

    asyncio.run(_run())
