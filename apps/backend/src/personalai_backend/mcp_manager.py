"""Manage MCP servers at runtime (M7): connect/disconnect live + persist to mcp.json.

The single source of truth is the ``mcp.json`` file (the ``mcpServers`` map). Connecting a server
registers its tools behind the gateway's tool registry (so the agent + Tools panel see them);
disconnecting unregisters them and closes the subprocess — no backend restart needed.

Best-effort: a server that fails to launch is recorded with its error and skipped; one bad server
never breaks startup or the others. Third-party MCP tools remain HIGH-risk (gateway approval).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from personalai_core import RegisteredTool
from personalai_core.registries import Registries
from personalai_tool_mcp import McpClient, McpServerConfig, read_servers, write_servers

logger = logging.getLogger(__name__)

ClientFactory = Callable[[McpServerConfig], Any]

# Sentinel returned in place of env secret values and accepted on writes to mean "keep the stored
# value". Never persist this literal; never reveal a real secret in an API response.
MASKED = "********"


def _spec_to_config(name: str, spec: dict[str, Any]) -> McpServerConfig:
    return McpServerConfig(
        name=name,
        command=str(spec.get("command") or ""),
        args=tuple(spec.get("args") or ()),
        env=spec.get("env") or None,
        url=spec.get("url") or None,
        headers=spec.get("headers") or None,
    )


def _mask_env(env: Mapping[str, str] | None) -> dict[str, str]:
    """Hide secret values (keys stay visible) for API responses."""
    return {k: (MASKED if v else "") for k, v in (env or {}).items()}


class McpManager:
    """Owns the connected MCP servers and the on-disk config."""

    def __init__(
        self,
        registries: Registries,
        path: Path,
        *,
        client_factory: ClientFactory = McpClient,
        egress_guard: Callable[[str], None] | None = None,
    ) -> None:
        self._registries = registries
        self._path = path
        self._factory = client_factory
        # Egress guard for remote (HTTP) MCP servers; loopback passes, others need the allowlist.
        self._egress_guard = egress_guard
        self._active: dict[str, tuple[Any, list[str]]] = {}  # name -> (client, tool names)
        self._status: dict[str, dict[str, Any]] = {}  # name -> {connected, tools, error}

    async def start(self) -> None:
        """Connect every enabled server defined in the config file (best-effort)."""
        for name, spec in read_servers(self._path).items():
            await self._apply(name, spec)

    def _public_server(self, name: str, spec: dict[str, Any]) -> dict[str, Any]:
        """One server's config (env secrets masked) merged with its live status."""
        status = self._status.get(name, {"connected": False, "tools": [], "error": None})
        return {
            "name": name,
            "command": spec.get("command", ""),
            "args": list(spec.get("args") or ()),
            "env": _mask_env(spec.get("env")),
            "url": spec.get("url"),
            "headers": _mask_env(spec.get("headers")),  # may carry auth -> mask values
            "enabled": spec.get("enabled", True),
            **status,
        }

    def list_servers(self) -> list[dict[str, Any]]:
        """Each configured server (env masked) merged with its live status."""
        return [self._public_server(n, s) for n, s in read_servers(self._path).items()]

    def config_json(self) -> dict[str, dict[str, Any]]:
        """The whole mcpServers map (env/header secrets masked) for the JSON editor / export."""
        out: dict[str, dict[str, Any]] = {}
        for name, spec in read_servers(self._path).items():
            entry: dict[str, Any] = {
                "command": spec.get("command", ""),
                "args": list(spec.get("args") or ()),
                "env": _mask_env(spec.get("env")),
                "enabled": spec.get("enabled", True),
            }
            if spec.get("url"):  # remote (HTTP) server
                entry["url"] = spec["url"]
                entry["headers"] = _mask_env(spec.get("headers"))
            out[name] = entry
        return out

    def _resolve_secrets(self, name: str, spec: dict[str, Any]) -> dict[str, Any]:
        """Replace masked values (``********``) in env + headers with the stored secret per key."""
        existing = read_servers(self._path).get(name, {})
        resolved = dict(spec)
        for field_name in ("env", "headers"):
            incoming = spec.get(field_name)
            if incoming is None:
                continue
            stored = existing.get(field_name, {})
            out: dict[str, str] = {}
            for key, value in incoming.items():
                if value == MASKED:
                    if key in stored:
                        out[key] = stored[key]  # keep the existing secret
                else:
                    out[key] = value
            resolved[field_name] = out
        return resolved

    async def upsert(self, name: str, spec: dict[str, Any]) -> dict[str, Any]:
        """Create or update a server, persist it, and apply live (connect if enabled)."""
        spec = self._resolve_secrets(name, spec)
        servers = read_servers(self._path)
        servers[name] = spec
        write_servers(self._path, servers)
        await self._apply(name, spec)
        return self._public_server(name, spec)

    async def import_servers(self, servers: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge a batch of servers into the config (write once) and apply each live."""
        resolved = {name: self._resolve_secrets(name, spec) for name, spec in servers.items()}
        current = read_servers(self._path)
        current.update(resolved)
        write_servers(self._path, current)
        for name, spec in resolved.items():
            await self._apply(name, spec)
        return self.list_servers()

    async def replace_config(self, desired: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace the whole config with ``desired`` and reconcile live (best-effort per server)."""
        resolved = {name: self._resolve_secrets(name, spec) for name, spec in desired.items()}
        current = read_servers(self._path)
        write_servers(self._path, resolved)  # single atomic-ish write of the new document
        for name in set(current) - set(resolved):  # removed -> disconnect + forget
            await self._disconnect(name)
            self._status.pop(name, None)
        for name, spec in resolved.items():
            if current.get(name) == spec and name in self._active:
                continue  # unchanged and already connected -> no churn
            await self._apply(name, spec)
        return self.list_servers()

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

    async def check_health(self, name: str) -> dict[str, Any] | None:
        """Probe one server's health (distinct from enabled/connected). None if unknown."""
        spec = read_servers(self._path).get(name)
        if spec is None:
            return None
        result: dict[str, Any] = {
            "name": name,
            "status": "disabled",
            "latency_ms": None,
            "tool_count": None,
            "error": None,
            "checked_at": datetime.now(UTC).isoformat(),
        }
        if not spec.get("enabled", True):
            return result
        started = perf_counter()
        entry = self._active.get(name)
        try:
            if entry is not None:  # connected -> lightweight live probe
                count = await asyncio.wait_for(entry[0].health(), timeout=10)
            else:  # stopped -> throwaway connect to verify it can launch
                self._check_remote_egress(spec)  # remote URL must pass the egress allowlist
                client = self._factory(_spec_to_config(name, spec))
                try:
                    count = len(await asyncio.wait_for(client.connect(), timeout=20))
                finally:
                    await client.aclose()
            result["status"] = "healthy"
            result["tool_count"] = count
        except Exception as exc:  # noqa: BLE001 - fail-closed: report, never raise
            result["status"] = "error" if entry is not None else "unreachable"
            result["error"] = str(exc)
        result["latency_ms"] = round((perf_counter() - started) * 1000)
        return result

    async def check_all(self) -> list[dict[str, Any]]:
        """Probe every configured server's health."""
        return [
            r for n in read_servers(self._path) if (r := await self.check_health(n)) is not None
        ]

    async def aclose(self) -> None:
        for name in list(self._active):
            await self._disconnect(name)

    def _check_remote_egress(self, spec: dict[str, Any]) -> None:
        """For a remote (HTTP) MCP server, enforce the egress allowlist on its URL host."""
        url = spec.get("url")
        if url and self._egress_guard is not None:
            self._egress_guard(urlparse(str(url)).hostname or str(url))

    async def _apply(self, name: str, spec: dict[str, Any]) -> None:
        """Reconcile one server to its spec: disconnect, then (re)connect if enabled."""
        await self._disconnect(name)
        if not spec.get("enabled", True):
            self._status[name] = {"connected": False, "tools": [], "error": None}
            return
        client = self._factory(_spec_to_config(name, spec))
        try:
            self._check_remote_egress(spec)  # remote URL must pass the egress allowlist
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
