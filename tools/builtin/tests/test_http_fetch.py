"""http_fetch tool: egress gating + fetch behavior (respx-mocked)."""

from __future__ import annotations

import asyncio

import httpx
import respx

from personalai_contracts.ports import ToolCall, ToolResult
from personalai_tool_builtin import HttpFetch


def _fetch(handler: HttpFetch, url: str) -> ToolResult:
    return asyncio.run(handler.invoke(ToolCall("http_fetch", "1.0.0", {"url": url})))


@respx.mock
def test_fetches_when_egress_allowed() -> None:
    respx.get("https://api.example.com/data").mock(
        return_value=httpx.Response(200, text="hello", headers={"content-type": "text/plain"})
    )
    result = _fetch(HttpFetch(lambda host: True), "https://api.example.com/data")
    assert result.ok
    assert result.output["status"] == 200
    assert result.output["body"] == "hello"
    assert result.output["content_type"] == "text/plain"


def test_blocked_when_egress_not_allowed() -> None:
    result = _fetch(HttpFetch(lambda host: False), "https://evil.example.com/x")
    assert not result.ok and "egress not allowed" in (result.error or "")


def test_rejects_non_http_url() -> None:
    result = _fetch(HttpFetch(lambda host: True), "ftp://example.com/x")
    assert not result.ok and "invalid url" in (result.error or "")


@respx.mock
def test_fetch_error_is_fail_closed() -> None:
    respx.get("https://api.example.com/boom").mock(side_effect=httpx.ConnectError("down"))
    result = _fetch(HttpFetch(lambda host: True), "https://api.example.com/boom")
    assert not result.ok and "fetch failed" in (result.error or "")


@respx.mock
def test_truncates_large_body() -> None:
    respx.get("https://api.example.com/big").mock(
        return_value=httpx.Response(200, text="x" * 50000)
    )
    result = _fetch(HttpFetch(lambda host: True, max_chars=100), "https://api.example.com/big")
    assert result.ok and len(result.output["body"]) == 100
