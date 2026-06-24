"""web_search tool: provider abstraction (DuckDuckGo / SearXNG / Tavily), result mapping, the
tool's tolerance of unknown args, empty-result handling, and clear error surfacing. httpx-mocked."""

from __future__ import annotations

import asyncio

import httpx
import respx

from personalai_contracts.ports import ToolCall, ToolResult
from personalai_tool_builtin import (
    DuckDuckGoSearch,
    SearxngSearch,
    TavilySearch,
    WebSearch,
    web_search_manifest,
)
from personalai_tool_builtin.web_search import DDG_HOST, parse_results

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

# results[].{title,url,content} — the shape SearXNG and Tavily both return.
_JSON = {
    "results": [
        {"title": "First Result", "url": "https://a.co", "content": "Snippet one."},
        {"title": "Second", "url": "https://b.co", "content": "Snippet two."},
    ]
}


def _search(handler: WebSearch, query: str, **args: object) -> ToolResult:
    return asyncio.run(handler.invoke(ToolCall("web_search", "1.0.0", {"query": query, **args})))


# --- DuckDuckGo adapter ------------------------------------------------------------------------


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
def test_duckduckgo_maps_html_to_results() -> None:
    respx.get("https://html.duckduckgo.com/html/").mock(
        return_value=httpx.Response(200, text=_HTML)
    )
    result = _search(WebSearch(DuckDuckGoSearch()), "example query")
    assert result.ok
    assert len(result.output["results"]) == 2
    assert result.output["results"][0]["title"] == "First Result"


@respx.mock
def test_duckduckgo_respects_max_results() -> None:
    respx.get("https://html.duckduckgo.com/html/").mock(
        return_value=httpx.Response(200, text=_HTML)
    )
    result = _search(WebSearch(DuckDuckGoSearch()), "q", max_results=1)
    assert len(result.output["results"]) == 1


def test_duckduckgo_host() -> None:
    assert DuckDuckGoSearch().host == DDG_HOST


# --- SearXNG adapter ---------------------------------------------------------------------------


@respx.mock
def test_searxng_maps_json_to_results() -> None:
    respx.get("http://127.0.0.1:8888/search").mock(return_value=httpx.Response(200, json=_JSON))
    provider = SearxngSearch("http://127.0.0.1:8888")
    assert provider.host == "127.0.0.1"  # egress host parsed from base_url (loopback)
    result = _search(WebSearch(provider), "q")
    assert result.ok
    assert result.output["results"][0] == {
        "title": "First Result",
        "url": "https://a.co",
        "snippet": "Snippet one.",
    }


@respx.mock
def test_searxng_empty_results_is_ok() -> None:
    respx.get("http://127.0.0.1:8888/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    result = _search(WebSearch(SearxngSearch("http://127.0.0.1:8888")), "q")
    assert result.ok and result.output["results"] == []


# --- Tavily adapter ----------------------------------------------------------------------------


@respx.mock
def test_tavily_maps_json_to_results() -> None:
    route = respx.post("https://api.tavily.com/search").mock(
        return_value=httpx.Response(200, json=_JSON)
    )
    provider = TavilySearch("tvly-secret")  # pragma: allowlist secret
    assert provider.host == "api.tavily.com"
    result = _search(WebSearch(provider), "q")
    assert result.ok
    assert result.output["results"][1]["url"] == "https://b.co"
    # only the supported params are sent (api_key, query, max_results)
    sent = route.calls.last.request
    import json as _json

    body = _json.loads(sent.content)
    assert set(body) == {"api_key", "query", "max_results"}


# --- The tool: unknown args, empty query, errors ------------------------------------------------


@respx.mock
def test_unknown_args_are_tolerated_and_search_still_runs() -> None:
    respx.get("https://html.duckduckgo.com/html/").mock(
        return_value=httpx.Response(200, text=_HTML)
    )
    # The model sometimes invents Tavily-style params; they must NOT break the call.
    result = _search(
        WebSearch(DuckDuckGoSearch()),
        "q",
        search_depth="advanced",
        include_raw_content=True,
        country="us",
    )
    assert result.ok and len(result.output["results"]) == 2


def test_empty_query_rejected() -> None:
    result = _search(WebSearch(DuckDuckGoSearch()), "   ")
    assert not result.ok and "empty query" in (result.error or "")


@respx.mock
def test_transport_error_is_clear_and_fail_closed() -> None:
    respx.get("https://html.duckduckgo.com/html/").mock(side_effect=httpx.ConnectError("down"))
    result = _search(WebSearch(DuckDuckGoSearch()), "q")
    assert not result.ok
    assert "unreachable" in (result.error or "")


@respx.mock
def test_http_status_error_includes_status() -> None:
    respx.post("https://api.tavily.com/search").mock(return_value=httpx.Response(429, json={}))
    result = _search(WebSearch(TavilySearch("k")), "q")  # pragma: allowlist secret
    assert not result.ok and "429" in (result.error or "")


# --- Dynamic manifest --------------------------------------------------------------------------


def test_manifest_egress_matches_active_provider_host() -> None:
    ddg = web_search_manifest(DuckDuckGoSearch().host)
    assert ddg.egress == (DDG_HOST,)
    assert ddg.permissions[0].scope == DDG_HOST

    searx = web_search_manifest(SearxngSearch("http://127.0.0.1:8888").host)
    assert searx.egress == ("127.0.0.1",)
    assert searx.permissions[0].scope == "127.0.0.1"
