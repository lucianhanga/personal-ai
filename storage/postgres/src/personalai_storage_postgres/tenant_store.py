"""Identity + tenancy store (ADR-0010): tenants, principals (subjects), memberships.

The data-model foundation for multi-tenancy (P0.1). Tenant scoping (tenant_id on domain tables) and
Row-Level Security come in later migrations; this store just manages the identity tables and is used
by the IdentityProvider/session layer (P1). MVP uses tenant=user, but the schema is org-ready.
"""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg

# The default tenant seeded by migration 0007 (local/personal/dev). Fixed so backfill + dev-login
# are deterministic.
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class Tenant:
    """A tenant — the isolation boundary. MVP: one per user; org-ready for teams later."""

    id: str
    name: str


@dataclass(frozen=True)
class Subject:
    """A principal (a human user or a service) that authenticates and belongs to tenants."""

    id: str
    email: str | None
    display_name: str | None


def _tenant(row: asyncpg.Record) -> Tenant:
    return Tenant(id=str(row["id"]), name=row["name"])


def _subject(row: asyncpg.Record) -> Subject:
    return Subject(id=str(row["id"]), email=row["email"], display_name=row["display_name"])


class PgTenantStore:
    """CRUD for tenants, subjects, and memberships."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_tenant(self, name: str) -> Tenant:
        row = await self._pool.fetchrow(
            "INSERT INTO tenants(name) VALUES($1) RETURNING id, name", name
        )
        return _tenant(row)

    async def get_tenant(self, tenant_id: str) -> Tenant | None:
        row = await self._pool.fetchrow("SELECT id, name FROM tenants WHERE id = $1", tenant_id)
        return _tenant(row) if row else None

    async def create_subject(
        self, email: str | None = None, display_name: str | None = None
    ) -> Subject:
        normalized = email.strip().lower() if email else None
        row = await self._pool.fetchrow(
            "INSERT INTO subjects(email, display_name) VALUES($1, $2) "
            "RETURNING id, email, display_name",
            normalized,
            display_name,
        )
        return _subject(row)

    async def get_subject_by_email(self, email: str) -> Subject | None:
        row = await self._pool.fetchrow(
            "SELECT id, email, display_name FROM subjects WHERE email = $1",
            email.strip().lower(),
        )
        return _subject(row) if row else None

    async def set_password_hash(self, subject_id: str, password_hash: str) -> None:
        """Store the argon2id PHC string for a subject (never a plaintext)."""
        await self._pool.execute(
            "UPDATE subjects SET password_hash = $2 WHERE id = $1", subject_id, password_hash
        )

    async def get_password_hash(self, email: str) -> tuple[str, str] | None:
        """Return ``(subject_id, password_hash)`` for a login email, or None if no password set."""
        row = await self._pool.fetchrow(
            "SELECT id, password_hash FROM subjects WHERE email = $1", email.strip().lower()
        )
        if row is None or row["password_hash"] is None:
            return None
        return str(row["id"]), row["password_hash"]

    async def add_membership(self, tenant_id: str, subject_id: str, role: str = "member") -> None:
        await self._pool.execute(
            "INSERT INTO memberships(tenant_id, subject_id, role) VALUES($1, $2, $3) "
            "ON CONFLICT (tenant_id, subject_id) DO UPDATE SET role = EXCLUDED.role",
            tenant_id,
            subject_id,
            role,
        )

    async def memberships_for_subject(self, subject_id: str) -> list[tuple[str, str]]:
        """Return ``(tenant_id, role)`` for each tenant the subject belongs to."""
        rows = await self._pool.fetch(
            "SELECT tenant_id, role FROM memberships WHERE subject_id = $1 ORDER BY created_at",
            subject_id,
        )
        return [(str(r["tenant_id"]), r["role"]) for r in rows]
