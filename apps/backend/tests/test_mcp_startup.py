"""Connecting configured MCP servers + registering their tools (fake clients, no subprocess)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from personalai_backend.mcp_startup import connect_mcp_servers
from personalai_contracts.ports import ToolCall, ToolResult
from personalai_contracts.schemas.tools import Provenance, RiskLevel, ToolManifest
from personalai_core import CoreConfig
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

    async def aclose(self) -> None:
        self.closed = True


class _FailClient(_FakeClient):
    async def connect(self) -> list[tuple[ToolManifest, _FakeHandler]]:
        raise RuntimeError("no binary")


def _cfg(tmp_path: Path) -> CoreConfig:
    p = tmp_path / "mcp.json"
    p.write_text('{"mcpServers": {"pw": {"command": "npx", "args": ["x"]}}}', encoding="utf-8")
    return CoreConfig(mcp_config_path=str(p))


def test_no_config_connects_nothing() -> None:
    clients, status = asyncio.run(connect_mcp_servers(CoreConfig(), Registries()))
    assert clients == [] and status == []


def test_connect_registers_tools(tmp_path: Path) -> None:
    regs = Registries()
    clients, status = asyncio.run(
        connect_mcp_servers(_cfg(tmp_path), regs, client_factory=_FakeClient)
    )
    assert len(clients) == 1
    assert status[0] == {"name": "pw", "connected": True, "tools": ["pw.do"], "error": None}
    assert "pw.do" in regs.tools.names()  # registered behind the gateway's tool registry


def test_connect_failure_recorded_and_closed(tmp_path: Path) -> None:
    captured: list[_FailClient] = []

    def factory(server: object) -> _FailClient:
        c = _FailClient(server)
        captured.append(c)
        return c

    regs = Registries()
    clients, status = asyncio.run(connect_mcp_servers(_cfg(tmp_path), regs, client_factory=factory))
    assert clients == []
    assert not status[0]["connected"] and "no binary" in status[0]["error"]
    assert captured[0].closed  # partial client cleaned up
    assert "pw.do" not in regs.tools.names()
