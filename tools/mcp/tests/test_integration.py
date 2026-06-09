"""Opt-in MCP integration test against a real server (skipped in CI).

Run with:  PERSONALAI_MCP_IT=1 uv run pytest tools/mcp/tests/test_integration.py -q
Needs Node/npx (+ network for the first @playwright/mcp fetch). Override the server via
PERSONALAI_MCP_IT_CMD / PERSONALAI_MCP_IT_ARGS (comma-separated).
"""

from __future__ import annotations

import asyncio
import os

import pytest

from personalai_tool_mcp import McpClient, McpServerConfig

IT = os.environ.get("PERSONALAI_MCP_IT") == "1"
CMD = os.environ.get("PERSONALAI_MCP_IT_CMD", "npx")
ARGS = tuple(os.environ.get("PERSONALAI_MCP_IT_ARGS", "-y,@playwright/mcp@latest").split(","))


@pytest.mark.skipif(not IT, reason="set PERSONALAI_MCP_IT=1 to run against a real MCP server")
def test_connect_lists_and_wraps_tools() -> None:
    async def _run() -> list[str]:
        client = McpClient(McpServerConfig(name="it", command=CMD, args=ARGS))
        try:
            tools = await client.connect()
            return [m.name for m, _ in tools]
        finally:
            await client.aclose()

    names = asyncio.run(_run())
    assert names, "the MCP server should expose at least one tool"
    assert all(n.startswith("it.") for n in names)  # namespaced <server>.<tool>
