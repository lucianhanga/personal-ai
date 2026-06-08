"""Tool API: list + invoke through the gateway (no DB needed)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import bootstrap
from personalai_core import CoreConfig

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _client() -> TestClient:
    return TestClient(create_app(bootstrap(config=CoreConfig(auth_token=TOKEN))))


def test_list_tools() -> None:
    client = _client()
    data = client.get("/api/tools", headers=AUTH).json()["data"]["tools"]
    names = {t["name"]: t for t in data}
    assert "calculator" in names and "http_fetch" in names
    assert names["http_fetch"]["risk"] == "high"
    assert any(p["type"] == "network" for p in names["http_fetch"]["permissions"])


def test_tools_require_token() -> None:
    assert _client().get("/api/tools").status_code == 401


def test_invoke_calculator() -> None:
    client = _client()
    resp = client.post(
        "/api/tools/invoke",
        headers=AUTH,
        json={"tool": "calculator", "version": "1.0.0", "args": {"expression": "2 + 3 * 4"}},
    ).json()
    assert resp["ok"] is True
    assert resp["data"]["result"] == 14.0


def test_invoke_http_fetch_denied_without_approval() -> None:
    client = _client()
    resp = client.post(
        "/api/tools/invoke",
        headers=AUTH,
        json={"tool": "http_fetch", "version": "1.0.0", "args": {"url": "http://example.com"}},
    ).json()
    assert resp["ok"] is False
    assert resp["error"]["code"] == "E_TOOL"


def test_invoke_http_fetch_with_grant_then_egress_blocked() -> None:
    client = _client()
    resp = client.post(
        "/api/tools/invoke",
        headers=AUTH,
        json={
            "tool": "http_fetch",
            "version": "1.0.0",
            "args": {"url": "http://example.com"},
            "grants": [{"type": "network", "scope": "*"}],
            "approved": True,
        },
    ).json()
    assert resp["ok"] is False
    assert "egress not allowed" in resp["error"]["message"]


def test_invoke_invalid_grant_type_is_400() -> None:
    client = _client()
    resp = client.post(
        "/api/tools/invoke",
        headers=AUTH,
        json={
            "tool": "calculator",
            "version": "1.0.0",
            "args": {"expression": "1"},
            "grants": [{"type": "telepathy", "scope": "*"}],
        },
    )
    assert resp.status_code == 400
