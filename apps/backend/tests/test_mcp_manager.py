"""McpManager: live connect/disconnect + file persistence (fake clients, no subprocess)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from personalai_backend.mcp_manager import McpManager
from personalai_contracts.ports import ToolCall, ToolResult
from personalai_contracts.schemas.tools import Provenance, RiskLevel, ToolManifest
from personalai_core.registries import Registries


class _FakeHandler:
    def __init__(self, name: str) -> None:
        self.name = name

    async def invoke(self, call: ToolCall) -> ToolResult:
        return ToolResult(ok=True)


class _FakeClient:
    def __init__(self, server: object) -> None:
        self.server = server
        self.closed = False

    async def connect(self) -> list[tuple[ToolManifest, _FakeHandler]]:
        name = f"{self.server.name}.do"  # type: ignore[attr-defined]
        m = ToolManifest(
            name=name, version="mcp-1", provenance=Provenance(maintainer="x"), risk=RiskLevel.HIGH
        )
        return [(m, _FakeHandler(name))]

    async def health(self) -> int:
        return 1

    async def aclose(self) -> None:
        self.closed = True


class _FailClient(_FakeClient):
    async def connect(self) -> list[tuple[ToolManifest, _FakeHandler]]:
        raise RuntimeError("no binary")


def _mgr(tmp_path: Path, factory=_FakeClient) -> tuple[McpManager, Registries, Path]:  # type: ignore[no-untyped-def]
    regs = Registries()
    path = tmp_path / "mcp.json"
    return McpManager(regs, path, client_factory=factory), regs, path


def test_upsert_connects_persists_and_registers(tmp_path: Path) -> None:
    mgr, regs, path = _mgr(tmp_path)
    server = asyncio.run(mgr.upsert("pw", {"command": "npx", "args": ["x"], "enabled": True}))
    assert server["connected"] and server["tools"] == ["pw.do"]
    assert "pw.do" in regs.tools.names()  # registered behind the gateway
    # persisted to the file
    saved = json.loads(path.read_text())["mcpServers"]["pw"]
    assert saved["command"] == "npx" and saved["enabled"] is True


def test_disabled_server_persisted_but_not_connected(tmp_path: Path) -> None:
    mgr, regs, _ = _mgr(tmp_path)
    server = asyncio.run(mgr.upsert("pw", {"command": "npx", "enabled": False}))
    assert not server["connected"] and server["tools"] == []
    assert "pw.do" not in regs.tools.names()


def test_failed_connect_recorded(tmp_path: Path) -> None:
    mgr, regs, _ = _mgr(tmp_path, factory=_FailClient)
    server = asyncio.run(mgr.upsert("bad", {"command": "nope", "enabled": True}))
    assert not server["connected"] and "no binary" in server["error"]
    assert regs.tools.names() == ()


def test_update_reconnects_and_unregisters_old_tools(tmp_path: Path) -> None:
    mgr, regs, _ = _mgr(tmp_path)
    asyncio.run(mgr.upsert("pw", {"command": "npx", "enabled": True}))
    assert "pw.do" in regs.tools.names()
    # disable it -> tools removed
    asyncio.run(mgr.upsert("pw", {"command": "npx", "enabled": False}))
    assert "pw.do" not in regs.tools.names()


def test_delete_disconnects_and_removes(tmp_path: Path) -> None:
    mgr, regs, path = _mgr(tmp_path)
    asyncio.run(mgr.upsert("pw", {"command": "npx", "enabled": True}))
    assert asyncio.run(mgr.delete("pw")) is True
    assert "pw.do" not in regs.tools.names()
    assert "pw" not in json.loads(path.read_text())["mcpServers"]
    assert asyncio.run(mgr.delete("missing")) is False


def test_replace_config_skips_unchanged_and_drops_unknown_masked(tmp_path: Path) -> None:
    mgr, regs, path = _mgr(tmp_path)
    asyncio.run(mgr.upsert("a", {"command": "x", "enabled": True}))  # connected
    desired = {
        "a": {"command": "x", "enabled": True},  # identical -> skip-unchanged branch
        # masked value, never stored -> dropped:
        "b": {"command": "y", "env": {"GHOST": "********"}, "enabled": True},
    }
    servers = asyncio.run(mgr.replace_config(desired))
    assert {s["name"] for s in servers} == {"a", "b"}
    assert "a.do" in regs.tools.names() and "b.do" in regs.tools.names()
    # a masked value with no stored secret is dropped (cannot be recovered)
    stored_b = json.loads(path.read_text())["mcpServers"]["b"]
    assert stored_b.get("env", {}) == {}


def test_health_connected_disabled_and_unreachable(tmp_path: Path) -> None:
    mgr, _regs, _path = _mgr(tmp_path)
    asyncio.run(mgr.upsert("up", {"command": "x", "enabled": True}))  # connected
    asyncio.run(mgr.upsert("off", {"command": "x", "enabled": False}))  # disabled
    h_up = asyncio.run(mgr.check_health("up"))
    assert h_up is not None
    assert h_up["status"] == "healthy" and h_up["tool_count"] == 1 and h_up["latency_ms"] >= 0
    h_off = asyncio.run(mgr.check_health("off"))
    assert h_off is not None and h_off["status"] == "disabled"
    assert asyncio.run(mgr.check_health("missing")) is None


def test_health_stopped_server_throwaway_connect_and_failure(tmp_path: Path) -> None:
    # enabled but not connected -> throwaway connect probe
    mgr, _regs, path = _mgr(tmp_path)
    import json as _json

    path.write_text(_json.dumps({"mcpServers": {"s": {"command": "x", "enabled": True}}}))
    h = asyncio.run(mgr.check_health("s"))  # not in _active -> throwaway connect (fake -> healthy)
    assert h is not None and h["status"] == "healthy" and h["tool_count"] == 1

    fdir = tmp_path / "f"
    fdir.mkdir()
    fail_mgr, _r, fp = _mgr(fdir, factory=_FailClient)
    fp.write_text(_json.dumps({"mcpServers": {"s": {"command": "x", "enabled": True}}}))
    hf = asyncio.run(fail_mgr.check_health("s"))
    assert hf is not None and hf["status"] == "unreachable" and "no binary" in hf["error"]
    assert asyncio.run(mgr.check_all())  # smoke: returns a list


def test_start_connects_enabled_from_file_and_aclose(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "a": {"command": "x", "enabled": True},
                    "b": {"command": "y", "enabled": False},
                }
            }
        )
    )
    regs = Registries()
    mgr = McpManager(regs, path, client_factory=_FakeClient)
    asyncio.run(mgr.start())
    listed = {s["name"]: s for s in mgr.list_servers()}
    assert listed["a"]["connected"] and not listed["b"]["connected"]
    assert "a.do" in regs.tools.names()
    asyncio.run(mgr.aclose())
    assert "a.do" not in regs.tools.names()  # unregistered on shutdown
