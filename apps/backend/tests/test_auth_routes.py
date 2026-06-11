"""Auth endpoints + SecurityContext resolver (P1.4). DB-gated where it touches storage."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from personalai_backend.app import create_app
from personalai_backend.composition import bootstrap
from personalai_core import CoreConfig
from personalai_storage_postgres import create_pool

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


_DB = pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")


def test_session_me_local_dev_login() -> None:
    client = TestClient(create_app(bootstrap(config=CoreConfig())))
    body = client.get("/api/v1/auth/session/me").json()["data"]
    assert body["auth_kind"] == "dev" and body["tenant_id"]


def test_hosted_session_me_requires_login() -> None:
    client = TestClient(create_app(bootstrap(config=CoreConfig(app_mode="hosted"))))
    assert client.get("/api/v1/auth/session/me").status_code == 401


@_DB
def test_signup_login_me_logout_flow() -> None:
    # `with` runs the lifespan so storage (DB) connects.
    with TestClient(
        create_app(bootstrap(config=CoreConfig(app_mode="hosted"))), base_url="https://testserver"
    ) as client:
        email = f"flow-{uuid.uuid4().hex[:8]}@example.com"
        assert (
            client.post("/api/v1/auth/signup", json={"email": email, "password": "pw"}).status_code
            == 200
        )
        # duplicate signup is still "accepted" (no enumeration)
        assert (
            client.post("/api/v1/auth/signup", json={"email": email, "password": "pw"}).status_code
            == 200
        )
        assert (
            client.post("/api/v1/auth/login", json={"email": email, "password": "bad"}).status_code
            == 401
        )
        ok = client.post("/api/v1/auth/login", json={"email": email, "password": "pw"})
        assert ok.status_code == 200 and ok.json()["data"]["tenant_id"]

        me = client.get("/api/v1/auth/session/me")  # cookie now set on the client
        assert me.status_code == 200 and me.json()["data"]["auth_kind"] == "cookie"

        assert client.post("/api/v1/auth/logout").status_code == 204
        assert client.get("/api/v1/auth/session/me").status_code == 401  # session revoked


@_DB
def test_hosted_csrf_blocks_then_allows_with_token() -> None:
    with TestClient(
        create_app(bootstrap(config=CoreConfig(app_mode="hosted"))), base_url="https://testserver"
    ) as client:
        email = f"csrf-{uuid.uuid4().hex[:8]}@example.com"
        client.post("/api/v1/auth/signup", json={"email": email, "password": "pw"})
        client.post("/api/v1/auth/login", json={"email": email, "password": "pw"})
        # Unsafe cookie-authenticated request WITHOUT the CSRF header is rejected (403)...
        assert client.post("/api/v1/conversations", json={"title": "x"}).status_code == 403
        # ...and WITH a matching X-CSRF-Token it passes the CSRF gate (not 403).
        csrf = client.cookies.get("pai_csrf")
        resp = client.post(
            "/api/v1/conversations", json={"title": "x"}, headers={"X-CSRF-Token": csrf or ""}
        )
        assert resp.status_code != 403


@_DB
def test_local_login_sets_cookie_and_logout() -> None:
    # Local mode login exercises the non-hosted cookie path (no Secure, no CSRF cookie).
    with TestClient(create_app(bootstrap(config=CoreConfig()))) as client:
        email = f"local-{uuid.uuid4().hex[:8]}@example.com"
        client.post("/api/v1/auth/signup", json={"email": email, "password": "pw"})
        assert (
            client.post("/api/v1/auth/login", json={"email": email, "password": "pw"}).status_code
            == 200
        )
        me = client.get("/api/v1/auth/session/me")
        assert me.status_code == 200 and me.json()["data"]["auth_kind"] == "cookie"
        assert client.post("/api/v1/auth/logout").status_code == 204


def test_local_logout_without_cookie_is_noop() -> None:
    # No session cookie present -> logout still returns 204 (covers the no-cookie branch).
    client = TestClient(create_app(bootstrap(config=CoreConfig())))
    assert client.post("/api/v1/auth/logout").status_code == 204


@_DB
def test_invalid_cookie_is_denied() -> None:
    with TestClient(
        create_app(bootstrap(config=CoreConfig(app_mode="hosted"))), base_url="https://testserver"
    ) as client:
        client.cookies.set("__Host-pai_session", "bogus-token")
        assert client.get("/api/v1/auth/session/me").status_code == 401
        # logout with a cookie that maps to no live session still succeeds (nothing to revoke)
        assert client.post("/api/v1/auth/logout").status_code == 204


def test_cookie_without_storage_is_denied() -> None:
    # Cookie present but storage unavailable -> deny (cannot validate the session).
    client = TestClient(
        create_app(
            bootstrap(
                config=CoreConfig(
                    app_mode="hosted", database_url="postgresql://nope@127.0.0.1:1/none"
                )
            )
        ),
        base_url="https://testserver",
    )
    client.cookies.set("__Host-pai_session", "anything")
    assert client.get("/api/v1/auth/session/me").status_code == 401


def test_login_without_storage_is_503() -> None:
    # No DB wired (storage None) -> auth endpoints that need it report 503, not 500.
    client = TestClient(
        create_app(
            bootstrap(
                config=CoreConfig(
                    app_mode="hosted", database_url="postgresql://nope@127.0.0.1:1/none"
                )
            )
        )
    )
    resp = client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "p"})
    assert resp.status_code == 503
