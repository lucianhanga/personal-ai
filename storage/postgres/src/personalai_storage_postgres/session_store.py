"""Server-side session store (ADR-0010, P1.3).

Opaque high-entropy tokens; only their sha256 hash is stored. Each session has a sliding idle
window and a hard absolute cap; ``get`` validates both and slides the idle window. Sessions are
revocable (logout / revoke-all on password reset). Identity-layer table — looked up by token hash
before a tenant context exists, so it is not RLS-gated.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import asyncpg

from personalai_contracts.ports import Session


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PgSessionStore:
    """Postgres-backed opaque, revocable sessions."""

    def __init__(
        self, pool: asyncpg.Pool, *, idle_seconds: int = 86_400, absolute_seconds: int = 604_800
    ) -> None:
        self._pool = pool
        self._idle = idle_seconds
        self._absolute = absolute_seconds

    async def create(self, tenant_id: str, subject_id: str) -> tuple[str, Session]:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        idle = now + timedelta(seconds=self._idle)
        absolute = now + timedelta(seconds=self._absolute)
        row = await self._pool.fetchrow(
            "INSERT INTO sessions(subject_id, tenant_id, token_hash, idle_expires_at, "
            "absolute_expires_at) VALUES($1, $2, $3, $4, $5) RETURNING id",
            subject_id,
            tenant_id,
            _hash(token),
            idle,
            absolute,
        )
        session = Session(
            id=str(row["id"]),
            subject_id=subject_id,
            tenant_id=tenant_id,
            expires_at=min(idle, absolute),
        )
        return token, session

    async def get(self, raw_token: str) -> Session | None:
        now = datetime.now(UTC)
        row = await self._pool.fetchrow(
            "SELECT id, subject_id, tenant_id, idle_expires_at, absolute_expires_at "
            "FROM sessions WHERE token_hash = $1",
            _hash(raw_token),
        )
        if row is None or row["idle_expires_at"] < now or row["absolute_expires_at"] < now:
            return None  # missing or expired => fail-closed
        new_idle = min(now + timedelta(seconds=self._idle), row["absolute_expires_at"])
        await self._pool.execute(
            "UPDATE sessions SET last_seen_at = $2, idle_expires_at = $3 WHERE id = $1",
            row["id"],
            now,
            new_idle,
        )
        return Session(
            id=str(row["id"]),
            subject_id=str(row["subject_id"]),
            tenant_id=str(row["tenant_id"]),
            expires_at=min(new_idle, row["absolute_expires_at"]),
        )

    async def revoke(self, session_id: str) -> None:
        await self._pool.execute("DELETE FROM sessions WHERE id = $1", session_id)

    async def revoke_all_for_subject(self, subject_id: str) -> None:
        await self._pool.execute("DELETE FROM sessions WHERE subject_id = $1", subject_id)
