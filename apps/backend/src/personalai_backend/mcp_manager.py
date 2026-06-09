"""Manage MCP servers at runtime (M7): connect/disconnect live + persist to mcp.json.

The single source of truth is the ``mcp.json`` file (the ``mcpServers`` map). Connecting a server
registers its tools behind the gateway's tool registry (so the agent + Tools panel see them);
disconnecting unregisters them and closes the subprocess — no backend restart needed.

Best-effort: a server that fails to launch is recorded with its error and skipped; one bad server
never breaks startup or the others. Third-party MCP tools remain HIGH-risk (gateway approval).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from personalai_core import RegisteredTool
from personalai_core.registries import Registries
from personalai_tool_mcp import McpClient, McpServerConfig, read_servers, write_servers

logger = logging.getLogger(__name__)

ClientFactory = Callable[[McpServerConfig], Any]


def _spec_to_config(name: str, spec: dict[str, Any]) -> McpServerConfig:
    return McpServerConfig(
        name=name,
        command=str(spec.get("command") or ""),
        args=tuple(spec.get("args") or ()),
        env=spec.get("env") or None,
    )


class McpManager:
    """Owns the connected MCP servers and the on-disk config."""

    def __init__(
        self, registries: Registries, path: Path, *, client_factory: ClientFactory = McpClient
    ) -> None:
        self._registries = registries
        self._path = path
        self._factory = client_factory
        self._active: dict[str, tuple[Any, list[str]]] = {}  # name -> (client, tool names)
        self._status: dict[str, dict[str, Any]] = {}  # name -> {connected, tools, error}

    async def start(self) -> None:
        """Connect every enabled server defined in the config file (best-effort)."""
        for name, spec in read_servers(self._path).items():
            await self._apply(name, spec)

    def list(self) -> list[dict[str, Any]]:
        """Each configured server merged with its live status (config + connected/tools/error)."""
        out: list[dict[str, Any]] = []
        for name, spec in read_servers(self._path).items():
            status = self._status.get(name, {"connected": False, "tools": [], "error": None})
            out.append(
                {
                    "name": name,
                    "command": spec.get("command", ""),
                    "args": list(spec.get("args") or ()),
                    "env": dict(spec.get("env") or {}),
                    "enabled": spec.get("enabled", True),
                    **status,
                }
            )
        return out

    async def upsert(self, name: str, spec: dict[str, Any]) -> dict[str, Any]:
        """Create or update a server, persist it, and apply live (connect if enabled)."""
        servers = read_servers(self._path)
        servers[name] = spec
        write_servers(self._path, servers)
        await self._apply(name, spec)
        return next(s for s in self.list() if s["name"] == name)

    async def delete(self, name: str) -> bool:
        """Disconnect (if connected) and remove the server from the config. False if unknown."""
        servers = read_servers(self._path)
        if name not in servers:
            return False
        await self._disconnect(name)
        self._status.pop(name, None)
        del servers[name]
        write_servers(self._path, servers)
        return True

    async def aclose(self) -> None:
        for name in list(self._active):
            await self._disconnect(name)

    async def _apply(self, name: str, spec: dict[str, Any]) -> None:
        """Reconcile one server to its spec: disconnect, then (re)connect if enabled."""
        await self._disconnect(name)
        if not spec.get("enabled", True):
            self._status[name] = {"connected": False, "tools": [], "error": None}
            return
        client = self._factory(_spec_to_config(name, spec))
        try:
            tools = await client.connect()
        except Exception as exc:  # noqa: BLE001 - one bad server must not break the others
            logger.warning("MCP server %r failed to connect: %s", name, exc)
            await client.aclose()
            self._status[name] = {"connected": False, "tools": [], "error": str(exc)}
            return
        names: list[str] = []
        for manifest, handler in tools:
            self._registries.tools.register(
                manifest.name, RegisteredTool(manifest, handler), overwrite=True
            )
            names.append(manifest.name)
        self._active[name] = (client, names)
        self._status[name] = {"connected": True, "tools": names, "error": None}
        logger.info("MCP server %r connected: %d tool(s)", name, len(names))

    async def _disconnect(self, name: str) -> None:
        entry = self._active.pop(name, None)
        if entry is None:
            return
        client, tool_names = entry
        for tool_name in tool_names:
            self._registries.tools.unregister(tool_name)
        await client.aclose()
