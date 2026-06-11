"""Ports: identity, authentication, and the request security context (ADR-0010).

The seams for always-on multi-tenant auth. ``IdentityProvider`` has a built-in adapter (argon2id
passwords / WebAuthn passkeys) today and an OIDC adapter later — drop-in, no core change (ADR-0001).
``SecurityContext`` is the fail-closed, request-scoped principal+tenant that flows through every
port, repository, the audit log, the agent loop, and the Tool/MCP gateway.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

AuthKind = Literal["cookie", "api_key", "dev", "oidc"]


@dataclass(frozen=True)
class SecurityContext:
    """The authenticated principal + tenant for one request. No context => deny (fail-closed)."""

    subject_id: str
    tenant_id: str
    auth_kind: AuthKind = "cookie"
    scopes: frozenset[str] = field(default_factory=frozenset)
    session_id: str | None = None


@dataclass(frozen=True)
class AuthResult:
    """A successful authentication: the principal and the tenant it resolved to."""

    subject_id: str
    tenant_id: str


@dataclass(frozen=True)
class Session:
    """A server-side, revocable session (the opaque cookie token maps to this)."""

    id: str
    subject_id: str
    tenant_id: str
    expires_at: datetime


@runtime_checkable
class IdentityProvider(Protocol):
    """Authenticates principals. Built-in (password/passkey) now; OIDC later."""

    async def authenticate_password(self, email: str, password: str) -> AuthResult | None:
        """Return the principal on valid credentials, else None (uniform, no enumeration)."""
        ...


@runtime_checkable
class SessionStore(Protocol):
    """Opaque, server-side, revocable sessions. The store keeps only a hash of the token."""

    async def create(self, tenant_id: str, subject_id: str) -> tuple[str, Session]:
        """Create a session; return ``(raw_token, session)`` (the raw token is the cookie value)."""
        ...

    async def get(self, raw_token: str) -> Session | None:
        """Return the live session for ``raw_token`` (validates + slides idle window), else None."""
        ...

    async def revoke(self, session_id: str) -> None:
        """Revoke one session (logout)."""
        ...

    async def revoke_all_for_subject(self, subject_id: str) -> None:
        """Revoke every session for a principal (e.g. on password reset)."""
        ...
