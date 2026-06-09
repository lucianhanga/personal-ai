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

from personalai_tool_mcp.client import McpServerConfig


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
        if not command:
            continue
        configs.append(
            McpServerConfig(
                name=name,
                command=command,
                args=tuple(entry.get("args") or ()),
                env=entry.get("env") or None,
            )
        )
    return configs
