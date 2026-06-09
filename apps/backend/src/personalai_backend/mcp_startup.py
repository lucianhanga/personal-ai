"""Connect configured MCP servers at startup and register their tools behind the gateway (M7).

Best-effort: a server that fails to launch/connect is recorded with its error and skipped — the app
still runs. Connected MCP tools register into the same tool registry the gateway + agent loop read,
so they are immediately callable (subject to the gateway's permission/risk/approval/audit checks;
third-party MCP tools default to HIGH risk, so they need the user's approval).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from personalai_core import CoreConfig, RegisteredTool
from personalai_core.registries import Registries
from personalai_tool_mcp import McpClient, McpServerConfig, load_server_configs

logger = logging.getLogger(__name__)

# Returns an McpClient (or a duck-typed fake in tests) with async connect()/aclose().
ClientFactory = Callable[[McpServerConfig], Any]


async def connect_mcp_servers(
    config: CoreConfig,
    registries: Registries,
    *,
    client_factory: ClientFactory = McpClient,
) -> tuple[list[McpClient], list[dict[str, Any]]]:
    """Connect each configured MCP server and register its tools. Returns (clients, status)."""
    if not config.mcp_config_path:
        return [], []
    servers = load_server_configs(Path(config.mcp_config_path))
    clients: list[McpClient] = []
    status: list[dict[str, Any]] = []
    for server in servers:
        client = client_factory(server)
        try:
            tools = await client.connect()
        except Exception as exc:  # noqa: BLE001 - one bad server must not break startup
            logger.warning("MCP server %r failed to connect: %s", server.name, exc)
            await client.aclose()
            status.append({"name": server.name, "connected": False, "tools": [], "error": str(exc)})
            continue
        for manifest, handler in tools:
            registries.tools.register(
                manifest.name, RegisteredTool(manifest, handler), overwrite=True
            )
        clients.append(client)
        names = [m.name for m, _ in tools]
        logger.info("MCP server %r connected: %d tool(s)", server.name, len(names))
        status.append({"name": server.name, "connected": True, "tools": names, "error": None})
    return clients, status
