"""Auth endpoints (ADR-0010, P1.4): signup, login, logout, session/me.

Built-in password auth. Errors are generic (no user enumeration). Login mints a server-side session
and sets the session cookie (+ a readable CSRF cookie in hosted mode). Identity tables are not
RLS-gated, so these handlers use the pool directly.
"""

from __future__ import annotations

import secrets

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from personalai_backend.auth.builtin import BuiltinIdentityProvider
from personalai_backend.auth.context import (
    CSRF_COOKIE,
    require_context,
    session_cookie_name,
)
from personalai_backend.auth.passwords import hash_password
from personalai_contracts.ports import SecurityContext
from personalai_contracts.schemas import StructuredResult
from personalai_storage_postgres import PgSessionStore, PgTenantStore

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str
    password: str


def _pool(request: Request) -> asyncpg.Pool:
    storage = request.app.state.storage
    if storage is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="storage unavailable"
        )
    return storage.pool


def _set_session_cookies(request: Request, response: Response, token: str) -> None:
    cfg = request.app.state.config
    hosted = cfg.app_mode == "hosted"
    response.set_cookie(
        session_cookie_name(cfg.app_mode),
        token,
        max_age=cfg.session_absolute_seconds,
        httponly=True,
        secure=hosted,
        samesite="strict" if hosted else "lax",
        path="/",
    )
    if hosted:
        # Double-submit CSRF: a readable token the SPA echoes in the X-CSRF-Token header.
        response.set_cookie(
            CSRF_COOKIE,
            secrets.token_urlsafe(32),
            max_age=cfg.session_absolute_seconds,
            httponly=False,
            secure=True,
            samesite="strict",
            path="/",
        )


@router.post("/signup", response_model=StructuredResult)
async def signup(request: Request, body: Credentials) -> StructuredResult:
    """Create a tenant + subject + membership with a password. Always accepted (no enumeration)."""
    tenants = PgTenantStore(_pool(request))
    try:
        subject = await tenants.create_subject(email=body.email)
    except Exception:  # noqa: BLE001 - duplicate email etc.: stay generic, do not enumerate
        return StructuredResult(ok=True, data={"status": "accepted"})
    tenant = await tenants.create_tenant(body.email.strip().lower())
    await tenants.add_membership(tenant.id, subject.id, role="owner")
    await tenants.set_password_hash(subject.id, hash_password(body.password))
    return StructuredResult(ok=True, data={"status": "accepted"})


@router.post("/login", response_model=StructuredResult)
async def login(request: Request, body: Credentials, response: Response) -> StructuredResult:
    pool = _pool(request)
    idp = BuiltinIdentityProvider(PgTenantStore(pool))
    result = await idp.authenticate_password(body.email, body.password)
    if result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    cfg = request.app.state.config
    sessions = PgSessionStore(
        pool,
        idle_seconds=cfg.session_idle_seconds,
        absolute_seconds=cfg.session_absolute_seconds,
    )
    token, _session = await sessions.create(result.tenant_id, result.subject_id)
    _set_session_cookies(request, response, token)
    return StructuredResult(
        ok=True, data={"subject_id": result.subject_id, "tenant_id": result.tenant_id}
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response) -> Response:
    cfg = request.app.state.config
    name = session_cookie_name(cfg.app_mode)
    raw = request.cookies.get(name)
    if raw is not None and request.app.state.storage is not None:
        sessions = PgSessionStore(request.app.state.storage.pool)
        session = await sessions.get(raw)
        if session is not None:
            await sessions.revoke(session.id)
    response.delete_cookie(name, path="/")
    if cfg.app_mode == "hosted":
        response.delete_cookie(CSRF_COOKIE, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/session/me", response_model=StructuredResult)
async def session_me(ctx: SecurityContext = Depends(require_context)) -> StructuredResult:
    return StructuredResult(
        ok=True,
        data={
            "subject_id": ctx.subject_id,
            "tenant_id": ctx.tenant_id,
            "auth_kind": ctx.auth_kind,
        },
    )
