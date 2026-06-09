"""web_search tool: DuckDuckGo HTML parsing + fetch behavior (respx-mocked)."""

from __future__ import annotations

import asyncio

import httpx
import respx

from personalai_contracts.ports import ToolCall, ToolResult
from personalai_tool_builtin import WebSearch
from personalai_tool_builtin.web_search import parse_results

_HTML = """
<a href="/about">nav link (ignored)</a>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.co">First Result</a>
  <a class="result__snippet">A snippet about the first result.</a>
</div>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fb.co">Second</a>
  <a class="result__snippet">Second snippet.</a>
</div>
"""


def _search(handler: WebSearch, query: str, **args: object) -> ToolResult:
    return asyncio.run(handler.invoke(ToolCall("web_search", "1.0.0", {"query": query, **args})))


def test_parse_results_decodes_redirect_and_pairs_snippets() -> None:
    results = parse_results(_HTML)
    assert len(results) == 2  # the nav link is ignored
    assert results[0] == {
        "title": "First Result",
        "url": "https://a.co",
        "snippet": "A snippet about the first result.",
    }
    assert results[1]["url"] == "https://b.co"


@respx.mock
def test_search_returns_parsed_results() -> None:
    respx.get("https://html.duckduckgo.com/html/").mock(
        return_value=httpx.Response(200, text=_HTML)
    )
    result = _search(WebSearch(), "example query")
    assert result.ok
    assert len(result.output["results"]) == 2
    assert result.output["results"][0]["title"] == "First Result"


@respx.mock
def test_search_respects_max_results() -> None:
    respx.get("https://html.duckduckgo.com/html/").mock(
        return_value=httpx.Response(200, text=_HTML)
    )
    result = _search(WebSearch(), "q", max_results=1)
    assert len(result.output["results"]) == 1


def test_empty_query_rejected() -> None:
    result = _search(WebSearch(), "   ")
    assert not result.ok and "empty query" in (result.error or "")


@respx.mock
def test_search_error_is_fail_closed() -> None:
    respx.get("https://html.duckduckgo.com/html/").mock(side_effect=httpx.ConnectError("down"))
    result = _search(WebSearch(), "q")
    assert not result.ok and "search failed" in (result.error or "")
