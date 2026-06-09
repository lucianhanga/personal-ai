"""PersonalAI MCP client adapter (M7): MCP-server tools behind the gateway."""

from personalai_tool_mcp.client import (
    McpClient,
    McpServerConfig,
    McpToolHandler,
    build_tools,
    manifest_from_mcp_tool,
)

__all__ = [
    "McpClient",
    "McpServerConfig",
    "McpToolHandler",
    "build_tools",
    "manifest_from_mcp_tool",
]
