"""HTTP behavior of the loopback API: health/version, auth, origin allowlist, structured output."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import bootstrap
from personalai_core import CoreConfig

TOKEN = "test-secret-token"


@pytest.fixture
def client() -> TestClient:
    config = CoreConfig(
        auth_token=TOKEN,
        allowed_origins=("http://localhost",),
        egress_enabled=False,
    )
    return TestClient(create_app(bootstrap(config=config)))


def test_health_is_public(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_version(client: TestClient) -> None:
    resp = client.get("/version")
    assert resp.status_code == 200
    assert resp.json()["name"] == "personalai-backend"


def test_protected_route_requires_token(client: TestClient) -> None:
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_protected_route_with_valid_token_returns_structured_result(client: TestClient) -> None:
    resp = client.get("/api/status", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["bind_host"] == "127.0.0.1"
    assert body["data"]["egress_enabled"] is False
    assert body["schema_version"] == "1.0.0"


def test_disallowed_origin_is_rejected(client: TestClient) -> None:
    resp = client.get("/health", headers={"Origin": "http://evil.example"})
    assert resp.status_code == 403


def test_allowed_origin_passes(client: TestClient) -> None:
    resp = client.get("/health", headers={"Origin": "http://localhost"})
    assert resp.status_code == 200


def test_auth_unconfigured_is_fail_closed() -> None:
    # No auth_token configured -> protected routes are unavailable (fail-closed), not open.
    client = TestClient(create_app(bootstrap(config=CoreConfig())))
    assert client.get("/api/status").status_code == 503


def test_non_loopback_bind_requires_auth_token() -> None:
    # Refuse to expose a non-loopback host without an auth token (fail-closed startup guard).
    config = CoreConfig(bind_host="0.0.0.0", auth_token=None)  # noqa: S104 - testing the guard
    with pytest.raises(RuntimeError, match="non-loopback host"):
        create_app(bootstrap(config=config))


def test_entrypoint_module_importable() -> None:
    # `python -m personalai_backend` entrypoint exists and is callable (not invoked here).
    import personalai_backend.__main__ as entry

    assert callable(entry.main)
