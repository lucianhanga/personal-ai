"""MCP adapter: tool->manifest mapping + handler proxying (fake caller, no subprocess)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from personalai_contracts.ports import ToolCall
from personalai_contracts.schemas.tools import RiskLevel
from personalai_tool_mcp import (
    McpClient,
    McpServerConfig,
    McpToolHandler,
    build_tools,
    manifest_from_mcp_tool,
)


@dataclass
class _FakeTool:
    name: str
    description: str = ""
    inputSchema: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Block:
    type: str
    text: str


@dataclass
class _FakeResult:
    content: list[_Block]
    isError: bool = False
    structuredContent: dict[str, Any] | None = None


class _FakeCaller:
    """Stands in for McpClient: records calls, returns/raises a scripted result."""

    def __init__(self, result: Any) -> None:
        self._result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, args: Mapping[str, Any]) -> Any:
        self.calls.append((name, dict(args)))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def test_manifest_namespaces_and_marks_untrusted() -> None:
    tool = _FakeTool(
        name="screenshot", description="take a screenshot", inputSchema={"type": "object"}
    )
    m = manifest_from_mcp_tool("playwright", tool)
    assert m.name == "playwright.screenshot"
    assert m.description == "take a screenshot"
    assert m.inputs == {"type": "object"}
    assert m.risk == RiskLevel.HIGH  # third-party MCP is untrusted
    assert m.provenance.maintainer == "mcp:playwright"


def test_handler_proxies_call_and_maps_result() -> None:
    caller = _FakeCaller(_FakeResult(content=[_Block("text", "ok!")], structuredContent={"n": 1}))
    handler = McpToolHandler("srv", "do", caller)
    assert handler.name == "srv.do"
    result = asyncio.run(handler.invoke(ToolCall("srv.do", "mcp-1", {"x": 2})))
    assert result.ok
    assert result.output == {"content": "ok!", "structured": {"n": 1}}
    assert caller.calls == [("do", {"x": 2})]  # MCP gets the un-namespaced name


def test_handler_success_without_structured_content() -> None:
    caller = _FakeCaller(_FakeResult(content=[_Block("text", "plain")]))
    result = asyncio.run(McpToolHandler("s", "t", caller).invoke(ToolCall("s.t", "mcp-1", {})))
    assert result.ok and result.output == {"content": "plain"}  # no "structured" key


def test_client_constructs_from_config() -> None:
    client = McpClient(McpServerConfig(name="pw", command="npx", args=("-y", "@playwright/mcp")))
    assert isinstance(client, McpClient)


def test_handler_maps_error_result_fail_closed() -> None:
    caller = _FakeCaller(_FakeResult(content=[_Block("text", "boom")], isError=True))
    result = asyncio.run(McpToolHandler("s", "t", caller).invoke(ToolCall("s.t", "mcp-1", {})))
    assert not result.ok and result.error == "boom"


def test_handler_catches_exceptions() -> None:
    caller = _FakeCaller(RuntimeError("transport down"))
    result = asyncio.run(McpToolHandler("s", "t", caller).invoke(ToolCall("s.t", "mcp-1", {})))
    assert not result.ok and "MCP call failed" in (result.error or "")


def test_build_tools_wraps_each() -> None:
    caller = _FakeCaller(_FakeResult(content=[]))
    tools = [_FakeTool(name="a"), _FakeTool(name="b")]
    built = build_tools("srv", caller, tools)
    assert [m.name for m, _ in built] == ["srv.a", "srv.b"]
    assert all(isinstance(h, McpToolHandler) for _, h in built)
