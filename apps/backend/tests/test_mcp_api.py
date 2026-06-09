"""GET /api/v1/mcp (no DB / no MCP servers configured)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import bootstrap
from personalai_core import CoreConfig

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _client() -> TestClient:
    return TestClient(create_app(bootstrap(config=CoreConfig(auth_token=TOKEN))))


def test_mcp_list_empty_without_config() -> None:
    with _client() as client:  # lifespan runs connect_mcp_servers (no config -> none)
        body = client.get("/api/v1/mcp", headers=AUTH).json()
    assert body["ok"] is True
    assert body["data"]["servers"] == []


def test_mcp_list_requires_token() -> None:
    with _client() as client:
        assert client.get("/api/v1/mcp").status_code == 401


def test_connected_mcp_servers_listed_and_closed_on_shutdown(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A connected server appears in /api/v1/mcp and is closed when the app shuts down."""
    from personalai_backend import app as app_module

    closed = {"v": False}

    class _FakeClient:
        async def aclose(self) -> None:
            closed["v"] = True

    async def _fake_connect(config, registries):  # type: ignore[no-untyped-def]
        status = [{"name": "pw", "connected": True, "tools": ["pw.go"], "error": None}]
        return [_FakeClient()], status

    monkeypatch.setattr(app_module, "connect_mcp_servers", _fake_connect)
    with _client() as client:
        servers = client.get("/api/v1/mcp", headers=AUTH).json()["data"]["servers"]
        assert servers == [{"name": "pw", "connected": True, "tools": ["pw.go"], "error": None}]
    assert closed["v"] is True  # aclose called on shutdown
