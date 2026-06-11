"""argon2id password hashing + the built-in IdentityProvider."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from personalai_backend.auth import BuiltinIdentityProvider, hash_password, verify_password
from personalai_storage_postgres import PgTenantStore, apply_migrations, create_pool

DB_URL = os.environ.get(
    "PERSONALAI_DATABASE_URL", "postgresql://personalai@127.0.0.1:5432/personalai"
)


def test_hash_and_verify_roundtrip() -> None:
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$") and h != "correct horse battery staple"
    assert verify_password(h, "correct horse battery staple") is True
    assert verify_password(h, "wrong") is False
    assert verify_password("not-a-hash", "x") is False  # fail-closed on bad hash


def _db_available() -> bool:
    async def _check() -> bool:
        try:
            pool = await create_pool(DB_URL)
        except Exception:
            return False
        await pool.close()
        return True

    return asyncio.run(_check())


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_builtin_identity_provider_authenticates() -> None:
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            tenants = PgTenantStore(pool)
            idp = BuiltinIdentityProvider(tenants)
            email = f"u-{uuid.uuid4().hex[:8]}@example.com"
            tenant = await tenants.create_tenant("Acme")
            subject = await tenants.create_subject(email=email)
            await tenants.set_password_hash(subject.id, hash_password("s3cret-pass"))
            await tenants.add_membership(tenant.id, subject.id)

            ok = await idp.authenticate_password(email, "s3cret-pass")
            assert ok is not None and ok.subject_id == subject.id and ok.tenant_id == tenant.id
            assert await idp.authenticate_password(email, "wrong") is None  # bad password
            assert await idp.authenticate_password("nobody@example.com", "x") is None  # unknown

            # a subject with a password but no tenant membership cannot sign in
            lonely = f"l-{uuid.uuid4().hex[:8]}@example.com"
            s2 = await tenants.create_subject(email=lonely)
            await tenants.set_password_hash(s2.id, hash_password("pw"))
            assert await idp.authenticate_password(lonely, "pw") is None
        finally:
            await pool.close()

    asyncio.run(_run())
