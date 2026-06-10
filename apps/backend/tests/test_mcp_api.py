"""MCP management API: list / upsert (live) / delete (no subprocess; fake client factory)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import bootstrap
from personalai_backend.mcp_manager import McpManager
from personalai_contracts.ports import ToolCall, ToolResult
from personalai_contracts.schemas.tools import Provenance, RiskLevel, ToolManifest
from personalai_core import CoreConfig

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class _FakeHandler:
    def __init__(self, name: str) -> None:
        self.name = name

    async def invoke(self, call: ToolCall) -> ToolResult:
        return ToolResult(ok=True)


class _FakeClient:
    def __init__(self, server: object) -> None:
        self.server = server

    async def connect(self) -> list[tuple[ToolManifest, _FakeHandler]]:
        name = f"{self.server.name}.do"  # type: ignore[attr-defined]
        m = ToolManifest(
            name=name, version="mcp-1", provenance=Provenance(maintainer="x"), risk=RiskLevel.HIGH
        )
        return [(m, _FakeHandler(name))]

    async def health(self) -> int:
        return 1

    async def aclose(self) -> None:
        pass


def _client(tmp_path: Path) -> TestClient:
    cfg = tmp_path / "mcp.json"
    boot = bootstrap(config=CoreConfig(auth_token=TOKEN, mcp_config_path=str(cfg)))
    app = create_app(boot)
    # Use the fake client factory so no real subprocess is spawned during the lifespan/upsert.
    app.state.mcp_manager = McpManager(boot.registries, cfg, client_factory=_FakeClient)
    return TestClient(app)


def test_list_empty_without_config(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        body = client.get("/api/v1/mcp", headers=AUTH).json()
    assert body["ok"] is True and body["data"]["servers"] == []


def test_list_requires_token(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.get("/api/v1/mcp").status_code == 401


def test_upsert_connects_and_lists(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        r = client.put(
            "/api/v1/mcp/servers/pw",
            headers=AUTH,
            json={"command": "npx", "args": ["x"], "env": {"K": "v"}, "enabled": True},
        )
        server = r.json()["data"]["server"]
        # env secret value is masked in the response (key visible, value hidden)
        assert (
            server["connected"]
            and server["tools"] == ["pw.do"]
            and server["env"] == {"K": "********"}
        )
        listed = client.get("/api/v1/mcp", headers=AUTH).json()["data"]["servers"]
        assert [s["name"] for s in listed] == ["pw"]


def test_secret_is_masked_and_round_trips(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.put(
            "/api/v1/mcp/servers/s", headers=AUTH, json={"command": "x", "env": {"TOKEN": "secret"}}
        )
        # GET never reveals the real secret
        got = client.get("/api/v1/mcp", headers=AUTH).json()["data"]["servers"][0]
        assert got["env"] == {"TOKEN": "********"}
        # editing other fields with the masked sentinel keeps the stored secret
        client.put(
            "/api/v1/mcp/servers/s",
            headers=AUTH,
            json={"command": "y", "env": {"TOKEN": "********"}},
        )
        # the on-disk file still has the real secret (sentinel was not persisted)
        import json

        stored = json.loads((tmp_path / "mcp.json").read_text())["mcpServers"]["s"]
        assert stored["command"] == "y" and stored["env"]["TOKEN"] == "secret"


def test_whole_config_get_and_replace(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.put("/api/v1/mcp/servers/a", headers=AUTH, json={"command": "x"})
        cfg = client.get("/api/v1/mcp/config", headers=AUTH).json()["data"]["mcpServers"]
        assert "a" in cfg
        # replace the whole document: drop "a", add "b"
        body = {"mcpServers": {"b": {"command": "y"}}}
        servers = client.put("/api/v1/mcp/config", headers=AUTH, json=body).json()["data"][
            "servers"
        ]
        assert [s["name"] for s in servers] == ["b"]  # a removed, b added/connected


def test_upsert_requires_command(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        bad = client.put("/api/v1/mcp/servers/x", headers=AUTH, json={"command": " "})
        assert bad.status_code == 400


def test_import_connects_multiple(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        body = {
            "mcpServers": {
                "a": {"command": "npx", "args": ["x"]},
                "b": {"command": "uvx", "enabled": False},
            }
        }
        servers = client.post("/api/v1/mcp/import", headers=AUTH, json=body).json()["data"][
            "servers"
        ]
        by_name = {s["name"]: s for s in servers}
        assert by_name["a"]["connected"] is True and by_name["a"]["tools"] == ["a.do"]
        assert by_name["b"]["connected"] is False  # imported but disabled


def test_import_rejects_empty_and_bad_entries(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert (
            client.post("/api/v1/mcp/import", headers=AUTH, json={"mcpServers": {}}).status_code
            == 400
        )
        bad = {"mcpServers": {"x": {"args": ["y"]}}}  # missing command
        assert client.post("/api/v1/mcp/import", headers=AUTH, json=bad).status_code == 422


def test_health_endpoints(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.put("/api/v1/mcp/servers/pw", headers=AUTH, json={"command": "npx"})
        one = client.post("/api/v1/mcp/servers/pw/health", headers=AUTH).json()["data"]["health"]
        assert one["status"] == "healthy" and one["tool_count"] == 1
        assert client.post("/api/v1/mcp/servers/nope/health", headers=AUTH).status_code == 404
        allh = client.post("/api/v1/mcp/health", headers=AUTH).json()["data"]["servers"]
        assert [h["name"] for h in allh] == ["pw"]


def test_mcp_log_lists_namespaced_tool_calls(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.put("/api/v1/mcp/servers/pw", headers=AUTH, json={"command": "npx"})
        # invoke the MCP tool through the gateway so it's audited
        client.post(
            "/api/v1/tools/invoke",
            headers=AUTH,
            json={"tool": "pw.do", "version": "mcp-1", "args": {}, "approved": True},
        )
        entries = client.get("/api/v1/mcp/log", headers=AUTH).json()["data"]["entries"]
        assert any(e["tool"] == "pw.do" for e in entries)
        # server filter
        scoped = client.get("/api/v1/mcp/log?server=pw", headers=AUTH).json()["data"]["entries"]
        assert all(str(e["tool"]).startswith("pw.") for e in scoped)
        assert (
            client.get("/api/v1/mcp/log?server=other", headers=AUTH).json()["data"]["entries"] == []
        )


def test_delete_removes(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.put("/api/v1/mcp/servers/pw", headers=AUTH, json={"command": "npx"})
        deleted = client.delete("/api/v1/mcp/servers/pw", headers=AUTH).json()["data"]["deleted"]
        assert deleted == "pw"
        assert client.get("/api/v1/mcp", headers=AUTH).json()["data"]["servers"] == []
        assert client.delete("/api/v1/mcp/servers/pw", headers=AUTH).status_code == 404
