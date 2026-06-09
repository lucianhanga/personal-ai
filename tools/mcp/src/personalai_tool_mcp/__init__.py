"""PersonalAI MCP client adapter (M7): MCP-server tools behind the gateway."""

from personalai_tool_mcp.client import (
    McpClient,
    McpServerConfig,
    McpToolHandler,
    build_tools,
    manifest_from_mcp_tool,
)
from personalai_tool_mcp.config import load_server_configs, read_servers, write_servers

__all__ = [
    "McpClient",
    "McpServerConfig",
    "McpToolHandler",
    "build_tools",
    "load_server_configs",
    "manifest_from_mcp_tool",
    "read_servers",
    "write_servers",
]
