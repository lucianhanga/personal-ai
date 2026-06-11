"""Built-in IdentityProvider (ADR-0010): argon2id password authentication.

Implements the `IdentityProvider` port using the tenant/subject store. Failures are uniform (no user
enumeration) and run a dummy verify on unknown emails so timing doesn't reveal whether an account
exists. OIDC/passkey adapters implement the same port later — no core change (ADR-0001).
"""

from __future__ import annotations

from personalai_backend.auth.passwords import hash_password, verify_password
from personalai_contracts.ports import AuthResult
from personalai_storage_postgres import PgTenantStore

# A real argon2 hash so authenticate() spends the same work whether or not the email exists.
_DUMMY_HASH = hash_password("password-does-not-matter")


class BuiltinIdentityProvider:
    """Authenticate principals against stored argon2id password hashes."""

    def __init__(self, tenants: PgTenantStore) -> None:
        self._tenants = tenants

    async def authenticate_password(self, email: str, password: str) -> AuthResult | None:
        cred = await self._tenants.get_password_hash(email)
        if cred is None:
            verify_password(_DUMMY_HASH, password)  # equalize timing for unknown emails
            return None
        subject_id, password_hash = cred
        if not verify_password(password_hash, password):
            return None
        memberships = await self._tenants.memberships_for_subject(subject_id)
        if not memberships:
            return None  # a subject with no tenant cannot sign in
        tenant_id, _role = memberships[0]  # MVP: one membership per subject
        return AuthResult(subject_id=subject_id, tenant_id=tenant_id)
