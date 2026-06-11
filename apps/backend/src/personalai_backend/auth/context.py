"""Request SecurityContext resolution + the require_context dependency (ADR-0010, P1.4).

Resolution precedence (first present wins; present-but-invalid => deny, no fall-through):
  1. cookie session  (the SPA in hosted mode)
  2. legacy bearer    (PERSONALAI_AUTH_TOKEN, a degenerate credential during the migration)
  3. dev-login        (local mode only: auto default-tenant context, no login screen)
  4. nothing          (hosted) => 401

The resolved context is stashed in ``current_security`` for the duration of the request so tenant-
scoped data access, the audit log, the agent loop, and the MCP manager can read it. Fail-closed.
"""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator

from fastapi import HTTPException, Request, status

from personalai_contracts.ports import SecurityContext
from personalai_core.security import current_security
from personalai_storage_postgres import DEFAULT_TENANT_ID, PgSessionStore

# Cookie name: __Host- prefix in hosted (requires Secure+https); plain in local (http loopback).
COOKIE_HOSTED = "__Host-pai_session"
COOKIE_LOCAL = "pai_session"
CSRF_COOKIE = "pai_csrf"
CSRF_HEADER = "x-csrf-token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_DEV_SUBJECT = "dev-local"


def session_cookie_name(app_mode: str) -> str:
    return COOKIE_HOSTED if app_mode == "hosted" else COOKIE_LOCAL


def _session_store(request: Request) -> PgSessionStore | None:
    storage = request.app.state.storage
    if storage is None:
        return None
    cfg = request.app.state.config
    return PgSessionStore(
        storage.pool,
        idle_seconds=cfg.session_idle_seconds,
        absolute_seconds=cfg.session_absolute_seconds,
    )


async def resolve_context(request: Request) -> SecurityContext | None:
    """Resolve the request's SecurityContext, or None if unauthenticated (fail-closed)."""
    cfg = request.app.state.config

    raw_cookie = request.cookies.get(session_cookie_name(cfg.app_mode))
    if raw_cookie is not None:
        store = _session_store(request)
        session = await store.get(raw_cookie) if store else None
        if session is None:
            return None  # present-but-invalid cookie => deny
        return SecurityContext(
            subject_id=session.subject_id,
            tenant_id=session.tenant_id,
            auth_kind="cookie",
            session_id=session.id,
        )

    # Token-protected mode: when a legacy bearer token is configured it is REQUIRED (no dev-login
    # fall-through), so a missing/invalid bearer is denied.
    if cfg.auth_token:
        authorization = request.headers.get("authorization")
        presented = (
            authorization[len("Bearer ") :]
            if authorization and authorization.startswith("Bearer ")
            else ""
        )
        if presented and hmac.compare_digest(presented, cfg.auth_token):
            return SecurityContext(
                subject_id="legacy-token", tenant_id=DEFAULT_TENANT_ID, auth_kind="api_key"
            )
        return None  # token configured but missing/invalid => deny

    # No token configured: local mode is zero-login (dev context); hosted requires a real session.
    if cfg.app_mode == "local":
        return SecurityContext(
            subject_id=_DEV_SUBJECT, tenant_id=DEFAULT_TENANT_ID, auth_kind="dev"
        )
    return None  # hosted + no credentials => deny


def _check_csrf(request: Request, ctx: SecurityContext) -> None:
    """Hosted-only double-submit CSRF check for cookie-authenticated unsafe requests."""
    cfg = request.app.state.config
    if cfg.app_mode != "hosted" or ctx.auth_kind != "cookie":
        return  # API keys + safe local mode are not cookie-CSRF exposed
    if request.method in _SAFE_METHODS:
        return
    header = request.headers.get(CSRF_HEADER)
    cookie = request.cookies.get(CSRF_COOKIE)
    if not header or not cookie or not hmac.compare_digest(header, cookie):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF check failed")


async def require_context(request: Request) -> AsyncIterator[SecurityContext]:
    """Resolve + enforce auth (401) + CSRF (403); bind current_security for the request."""
    ctx = await resolve_context(request)
    if ctx is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    _check_csrf(request, ctx)
    token = current_security.set(ctx)
    try:
        yield ctx
    finally:
        current_security.reset(token)
