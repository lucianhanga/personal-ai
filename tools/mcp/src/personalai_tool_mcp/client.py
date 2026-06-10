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

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from personalai_contracts.ports import ToolCall, ToolResult
from personalai_contracts.schemas.tools import Provenance, RiskLevel, ToolManifest

MCP_TOOL_VERSION = "mcp-1"


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


class _Caller(Protocol):
    """Something that can run a named MCP tool call (the McpClient, or a fake in tests)."""

    async def call(self, name: str, args: Mapping[str, Any]) -> Any: ...


class McpToolHandler:
    """A ToolHandler that proxies a single MCP tool call to the owning client."""

    def __init__(self, server_name: str, mcp_name: str, caller: _Caller) -> None:
        self.name = f"{server_name}.{mcp_name}"
        self._mcp_name = mcp_name
        self._caller = caller

    async def invoke(self, call: ToolCall) -> ToolResult:
        try:
            raw = await self._caller.call(self._mcp_name, dict(call.args))
        except Exception as exc:  # noqa: BLE001 - fail-closed: never raise out of a tool handler
            return ToolResult(ok=False, error=f"MCP call failed: {exc}")
        return _result_to_tool_result(raw)


def build_tools(
    server_name: str, caller: _Caller, tools: Sequence[Any]
) -> list[tuple[ToolManifest, McpToolHandler]]:
    """Wrap each MCP tool as a (manifest, handler) pair for registration behind the gateway."""
    return [
        (manifest_from_mcp_tool(server_name, t), McpToolHandler(server_name, t.name, caller))
        for t in tools
    ]


class McpClient:
    """A long-lived MCP stdio connection.

    The ``mcp`` SDK ties a stdio session to the task that opened it (anyio cancel scopes), so the
    session is opened, used for every call, and closed entirely inside a single **owner task**.
    ``connect``/``call``/``aclose`` hand work to that task over a queue, so different request tasks
    (chat, the management API) can drive one connection without cross-task cancel-scope errors.
    """

    def __init__(self, config: McpServerConfig) -> None:
        self._config = config
        self._task: asyncio.Task[None] | None = None
        # Queue items are (op, name, args, future); op is "call" or "health".
        self._requests: (
            asyncio.Queue[tuple[str, str, Mapping[str, Any], asyncio.Future[Any]]] | None
        ) = None
        self._stop: asyncio.Event | None = None

    async def connect(self) -> list[tuple[ToolManifest, McpToolHandler]]:  # pragma: no cover
        """Start the owner task, initialize the session, and return the wrapped tools.

        Requires a live MCP subprocess, so it is exercised by the opt-in integration test, not unit
        CI; the pure wrapping logic + handler are fully unit-tested.
        """
        loop = asyncio.get_running_loop()
        self._requests = asyncio.Queue()
        self._stop = asyncio.Event()
        ready: asyncio.Future[Sequence[Any]] = loop.create_future()
        self._task = asyncio.create_task(self._run(ready))
        tools = await ready  # raises if the server failed to launch/initialize
        return build_tools(self._config.name, self, tools)

    async def call(self, name: str, args: Mapping[str, Any]) -> Any:  # pragma: no cover
        """Run a tool call on the owner task and return the raw MCP result."""
        return await self._submit("call", name, dict(args))

    async def health(self) -> int:  # pragma: no cover
        """Probe the live session (list_tools) on the owner task; return the tool count."""
        return int(await self._submit("health", "", {}))

    async def _submit(self, op: str, name: str, args: Mapping[str, Any]) -> Any:  # pragma: no cover
        if self._requests is None:
            raise RuntimeError("MCP client is not connected")
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        await self._requests.put((op, name, args, fut))
        return await fut

    async def aclose(self) -> None:  # pragma: no cover - stops the owner task / live session
        if self._task is None:
            return
        if self._stop is not None:
            self._stop.set()
        await self._task
        self._task = None

    async def _run(self, ready: asyncio.Future[Sequence[Any]]) -> None:  # pragma: no cover
        """Owner task: open the session, serve calls until stopped, then close it (same task)."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self._config.command,
            args=list(self._config.args),
            env=dict(self._config.env) if self._config.env is not None else None,
        )
        assert self._requests is not None and self._stop is not None
        try:
            async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                ready.set_result(tools)
                while not self._stop.is_set():
                    get = asyncio.ensure_future(self._requests.get())
                    stop = asyncio.ensure_future(self._stop.wait())
                    done, pending = await asyncio.wait(
                        {get, stop}, return_when=asyncio.FIRST_COMPLETED
                    )
                    for p in pending:
                        p.cancel()
                    if get not in done:
                        continue
                    op, name, args, fut = get.result()
                    try:
                        if op == "health":
                            result: Any = len((await session.list_tools()).tools)
                        else:
                            result = await session.call_tool(name, dict(args))
                        fut.set_result(result)
                    except Exception as exc:  # noqa: BLE001 - report back to the caller
                        if not fut.done():
                            fut.set_exception(exc)
        except Exception as exc:  # noqa: BLE001 - surface launch/init failure to connect()
            if not ready.done():
                ready.set_exception(exc)
