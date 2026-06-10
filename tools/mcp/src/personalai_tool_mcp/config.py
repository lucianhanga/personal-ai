"""Load MCP server definitions from an ``mcp.json`` file.

Uses the de-facto-standard ``mcpServers`` map (the same shape Claude Desktop and other MCP hosts
use), so users can reuse existing config:

    {
      "mcpServers": {
        "playwright": { "command": "npx", "args": ["-y", "@playwright/mcp@latest"] }
      }
    }

An entry may set ``"enabled": false`` to keep it defined but not connect it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from personalai_tool_mcp.client import McpServerConfig


def read_servers(path: Path) -> dict[str, dict[str, Any]]:
    """Return the full ``mcpServers`` map (every entry, including disabled), ``{}`` if missing."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers") or data.get("servers") or {}
    return {name: dict(entry) for name, entry in servers.items() if isinstance(entry, dict)}


def write_servers(path: Path, servers: dict[str, dict[str, Any]]) -> None:
    """Persist the ``mcpServers`` map to ``path`` (creating parent dirs), pretty-printed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}, indent=2) + "\n", encoding="utf-8")


def load_server_configs(path: Path) -> list[McpServerConfig]:
    """Parse ``path`` and return the enabled stdio MCP server configs (``[]`` if missing/empty)."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers") or data.get("servers") or {}
    configs: list[McpServerConfig] = []
    for name, entry in servers.items():
        if not isinstance(entry, dict) or entry.get("enabled") is False:
            continue
        command = entry.get("command")
        url = entry.get("url")
        if not command and not url:  # need a stdio command or an HTTP url
            continue
        configs.append(
            McpServerConfig(
                name=name,
                command=command or "",
                args=tuple(entry.get("args") or ()),
                env=entry.get("env") or None,
                url=url or None,
                headers=entry.get("headers") or None,
            )
        )
    return configs
