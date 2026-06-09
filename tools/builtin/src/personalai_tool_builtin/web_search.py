"""A web-search tool backed by DuckDuckGo's HTML endpoint (no API key).

Declares a static egress host (``html.duckduckgo.com``), so the gateway enforces the egress
allowlist for it. Parses results with the stdlib HTML parser (no extra dependency) and decodes
DuckDuckGo's redirect links to the real URLs. MEDIUM risk (read-only network), swappable later for
SearXNG/Brave.
"""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import httpx

from personalai_contracts.ports import ToolCall, ToolResult
from personalai_contracts.schemas.tools import (
    Permission,
    PermissionType,
    Provenance,
    RiskLevel,
    ToolManifest,
)

DDG_HOST = "html.duckduckgo.com"

WEB_SEARCH_MANIFEST = ToolManifest(
    name="web_search",
    version="1.0.0",
    provenance=Provenance(maintainer="PersonalAI", license="Apache-2.0"),
    description="Search the web (DuckDuckGo) and return result titles, URLs, and snippets.",
    capabilities=["web.search"],
    permissions=(Permission(type=PermissionType.NETWORK, scope=DDG_HOST),),
    inputs={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer"},
        },
        "required": ["query"],
    },
    outputs={
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "snippet": {"type": "string"},
                    },
                },
            }
        },
        "required": ["results"],
    },
    egress=(DDG_HOST,),
    risk=RiskLevel.MEDIUM,
)


def _real_url(href: str) -> str:
    """Decode DuckDuckGo's redirect href (``...?uddg=<encoded real url>``)."""
    query = parse_qs(urlparse(href).query)
    return query.get("uddg", [href])[0]


class _ResultParser(HTMLParser):
    """Extract DuckDuckGo result links (``a.result__a``) and snippets (``a.result__snippet``)."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._mode: str | None = None  # "title" | "snippet"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr = dict(attrs)
        classes = (attr.get("class") or "").split()
        if "result__a" in classes:
            self._mode = "title"
            self.results.append(
                {"title": "", "url": _real_url(attr.get("href") or ""), "snippet": ""}
            )
        elif "result__snippet" in classes:
            self._mode = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._mode = None

    def handle_data(self, data: str) -> None:
        if not self.results:
            return
        if self._mode == "title":
            self.results[-1]["title"] += data.strip()
        elif self._mode == "snippet":
            self.results[-1]["snippet"] += data.strip()


def parse_results(html: str) -> list[dict[str, str]]:
    parser = _ResultParser()
    parser.feed(html)
    return [r for r in parser.results if r["title"] and r["url"]]


class WebSearch:
    """Search the web via DuckDuckGo's HTML endpoint."""

    name = "web_search"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
        max_results: int = 5,
    ) -> None:
        self._client = client
        self._timeout = timeout
        self._max_results = max_results

    async def invoke(self, call: ToolCall) -> ToolResult:
        query = str(call.args.get("query", "")).strip()
        if not query:
            return ToolResult(ok=False, error="empty query")
        raw_max = call.args.get("max_results")
        limit = int(raw_max) if isinstance(raw_max, int) else self._max_results

        client = self._client or httpx.AsyncClient(timeout=self._timeout, follow_redirects=False)
        try:
            response = await client.get(
                f"https://{DDG_HOST}/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (PersonalAI)"},
            )
            response.raise_for_status()
            return ToolResult(ok=True, output={"results": parse_results(response.text)[:limit]})
        except httpx.HTTPError as exc:
            return ToolResult(ok=False, error=f"search failed: {exc}")
        finally:
            if self._client is None:
                await client.aclose()
