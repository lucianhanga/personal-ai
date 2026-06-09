"""MCP client adapter (M7-1): expose an MCP server's tools as gateway tools.

Connects to an MCP server (stdio now), lists its tools, and wraps each as a (ToolManifest,
ToolHandler) pair. The composition root registers these behind the gateway, so MCP tools get the
same permission/egress/schema/risk/timeout/audit enforcement as built-in tools. Depends only on
``personalai_contracts`` and the official ``mcp`` SDK (ADR-0001).

Third-party MCP servers are untrusted: manifests default to ``RiskLevel.HIGH`` (so the gateway
requires explicit approval), declare no permissions/egress by default, and tool names are
namespaced ``<server>.<tool>`` to avoid collisions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from personalai_contracts.ports import ToolCall, ToolResult
from personalai_contracts.schemas.tools import Provenance, RiskLevel, ToolManifest

MCP_TOOL_VERSION = "mcp-1"

# An MCP client session (mcp.ClientSession, or a duck-typed fake in tests). Typed Any because the
# SDK's call_tool signature is broader than the slice we use.
Session = Any


@dataclass(frozen=True)
class McpServerConfig:
    """How to launch/reach an MCP server (stdio)."""

    name: str
    command: str
    args: Sequence[str] = field(default_factory=tuple)
    env: Mapping[str, str] | None = None


def manifest_from_mcp_tool(server_name: str, tool: Any) -> ToolManifest:
    """Build a ToolManifest from an MCP tool (duck-typed: name/description/inputSchema)."""
    input_schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
    return ToolManifest(
        name=f"{server_name}.{tool.name}",
        version=MCP_TOOL_VERSION,
        provenance=Provenance(maintainer=f"mcp:{server_name}"),
        description=getattr(tool, "description", "") or "",
        capabilities=("mcp",),
        inputs=dict(input_schema),
        outputs={},
        # Untrusted third-party code: require approval; declare nothing by default.
        risk=RiskLevel.HIGH,
    )


def _result_to_tool_result(raw: Any) -> ToolResult:
    """Map an MCP CallToolResult (content blocks + isError) to a normalized ToolResult."""
    blocks = getattr(raw, "content", None) or []
    text = "\n".join(
        getattr(b, "text", "") for b in blocks if getattr(b, "type", None) == "text"
    ).strip()
    structured = getattr(raw, "structuredContent", None)
    if getattr(raw, "isError", False):
        return ToolResult(ok=False, error=text or "MCP tool reported an error")
    output: dict[str, Any] = {"content": text}
    if isinstance(structured, dict):
        output["structured"] = structured
    return ToolResult(ok=True, output=output)


class McpToolHandler:
    """A ToolHandler that proxies a single MCP tool call to the server session."""

    def __init__(self, server_name: str, mcp_name: str, session: Session) -> None:
        self.name = f"{server_name}.{mcp_name}"
        self._mcp_name = mcp_name
        self._session = session

    async def invoke(self, call: ToolCall) -> ToolResult:
        try:
            raw = await self._session.call_tool(self._mcp_name, dict(call.args))
        except Exception as exc:  # noqa: BLE001 - fail-closed: never raise out of a tool handler
            return ToolResult(ok=False, error=f"MCP call failed: {exc}")
        return _result_to_tool_result(raw)


def build_tools(
    server_name: str, session: Session, tools: Sequence[Any]
) -> list[tuple[ToolManifest, McpToolHandler]]:
    """Wrap each MCP tool as a (manifest, handler) pair for registration behind the gateway."""
    return [
        (manifest_from_mcp_tool(server_name, t), McpToolHandler(server_name, t.name, session))
        for t in tools
    ]


class McpClient:
    """Manages a long-lived MCP stdio session and exposes its tools as gateway tools."""

    def __init__(self, config: McpServerConfig) -> None:
        self._config = config
        self._stack = AsyncExitStack()
        self._session: Session | None = None

    async def connect(self) -> list[tuple[ToolManifest, McpToolHandler]]:  # pragma: no cover
        """Spawn the stdio server, initialize the session, and return its wrapped tools.

        Requires a live MCP server subprocess, so it is exercised by the opt-in integration test
        (M7-5), not unit CI; the pure wrapping logic above is fully unit-tested.
        """
        # Imported here so the module (and its pure helpers) load without a live MCP runtime.
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self._config.command,
            args=list(self._config.args),
            env=dict(self._config.env) if self._config.env is not None else None,
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session
        tools = (await session.list_tools()).tools
        return build_tools(self._config.name, session, tools)

    async def aclose(self) -> None:  # pragma: no cover - closes the live stdio session (see M7-5)
        await self._stack.aclose()
        self._session = None
