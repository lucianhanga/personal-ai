"""A web-search tool with a configurable search-provider abstraction.

The tool delegates the actual search to a swappable :class:`WebSearchProvider` adapter, so the same
tool serves DuckDuckGo (zero-setup HTML scrape, no key), a self-hosted SearXNG JSON instance
(local-first), or Tavily (API key). Each provider exposes the egress ``host`` the gateway must
allow; the composition root builds the manifest's ``egress`` from the *active* provider's host so
the gateway enforces the allowlist against the host actually contacted.

No extra dependency: every adapter uses httpx (already a dep) and the stdlib HTML parser. MEDIUM
risk (read-only network), and the provider is selected from config (ADR-0001).
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Protocol, runtime_checkable
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
TAVILY_HOST = "api.tavily.com"

# Hard cap on results regardless of what the caller asks for (bounds payload + provider cost).
_MAX_RESULTS_CAP = 10


@runtime_checkable
class WebSearchProvider(Protocol):
    """A swappable search backend.

    ``search`` returns a list of ``{"title", "url", "snippet"}`` dicts (possibly empty — "no
    results" is a success, not an error). ``host`` is the egress host the gateway must allow for
    this provider; ``name`` is a short human label used in logs/diagnostics.
    """

    name: str

    @property
    def host(self) -> str:
        """The egress host the gateway must allow when this provider is active."""
        ...

    async def search(self, query: str, max_results: int) -> list[dict[str, str]]:
        """Run the search and return mapped results. Raises on transport/HTTP/protocol errors."""
        ...


# --- DuckDuckGo (zero-setup HTML scrape, no API key) -------------------------------------------


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


class DuckDuckGoSearch:
    """Scrape DuckDuckGo's HTML endpoint (``html.duckduckgo.com/html/``). No API key, zero setup."""

    name = "duckduckgo"

    def __init__(self, *, client: httpx.AsyncClient | None = None, timeout: float = 10.0) -> None:
        self._client = client
        self._timeout = timeout

    @property
    def host(self) -> str:
        return DDG_HOST

    async def search(self, query: str, max_results: int) -> list[dict[str, str]]:
        client = self._client or httpx.AsyncClient(timeout=self._timeout, follow_redirects=False)
        try:
            try:
                response = await client.get(
                    f"https://{DDG_HOST}/html/",
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0 (PersonalAI)"},
                )
            except httpx.HTTPError as exc:
                raise WebSearchError(f"search backend unreachable / blocked: {exc}") from exc
            if response.status_code >= 400:
                raise WebSearchError(
                    f"search backend returned HTTP {response.status_code} from {DDG_HOST}"
                )
            return parse_results(response.text)[:max_results]
        finally:
            if self._client is None:
                await client.aclose()


# --- SearXNG (self-hosted JSON API, local-first) -----------------------------------------------


class SearxngSearch:
    """Query a SearXNG instance JSON API (``GET {base_url}/search?q=...&format=json``).

    Maps ``results[].{title,url,content}`` -> ``{title,url,snippet}``. The egress host is parsed
    from ``base_url`` so a loopback instance is allowed when egress permits loopback.
    """

    name = "searxng"

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        parsed = urlparse(self._base_url)
        if not parsed.hostname:
            raise ValueError(f"searxng base_url has no host: {base_url!r}")
        self._host = parsed.hostname
        self._client = client
        self._timeout = timeout

    @property
    def host(self) -> str:
        return self._host

    async def search(self, query: str, max_results: int) -> list[dict[str, str]]:
        client = self._client or httpx.AsyncClient(timeout=self._timeout, follow_redirects=False)
        try:
            try:
                response = await client.get(
                    f"{self._base_url}/search",
                    params={"q": query, "format": "json"},
                    headers={"User-Agent": "PersonalAI"},
                )
            except httpx.HTTPError as exc:
                raise WebSearchError(f"search backend unreachable / blocked: {exc}") from exc
            if response.status_code >= 400:
                raise WebSearchError(
                    f"searxng returned HTTP {response.status_code} from {self._host}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise WebSearchError(f"searxng returned non-JSON response: {exc}") from exc
            results = payload.get("results") if isinstance(payload, dict) else None
            return _map_title_url_content(results, max_results)
        finally:
            if self._client is None:
                await client.aclose()


# --- Tavily (search API, requires an API key) --------------------------------------------------


class TavilySearch:
    """Query the Tavily search API (``POST {base_url}/search``).

    This is the API the models already expect — they invent its params (``search_depth``,
    ``include_raw_content``, ``country``); we only send the supported ones. Maps
    ``results[].{title,url,content}`` -> ``{title,url,snippet}``.
    """

    name = "tavily"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.tavily.com",
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        parsed = urlparse(self._base_url)
        self._host = parsed.hostname or TAVILY_HOST
        self._client = client
        self._timeout = timeout

    @property
    def host(self) -> str:
        return self._host

    async def search(self, query: str, max_results: int) -> list[dict[str, str]]:
        client = self._client or httpx.AsyncClient(timeout=self._timeout, follow_redirects=False)
        try:
            try:
                response = await client.post(
                    f"{self._base_url}/search",
                    json={
                        "api_key": self._api_key,
                        "query": query,
                        "max_results": max_results,
                    },
                )
            except httpx.HTTPError as exc:
                raise WebSearchError(f"search backend unreachable / blocked: {exc}") from exc
            if response.status_code >= 400:
                raise WebSearchError(
                    f"tavily returned HTTP {response.status_code} from {self._host}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise WebSearchError(f"tavily returned non-JSON response: {exc}") from exc
            results = payload.get("results") if isinstance(payload, dict) else None
            return _map_title_url_content(results, max_results)
        finally:
            if self._client is None:
                await client.aclose()


class WebSearchError(RuntimeError):
    """A clear, provider-agnostic search failure (transport, HTTP status, or bad payload)."""


def _map_title_url_content(results: object, max_results: int) -> list[dict[str, str]]:
    """Map a provider's ``results[].{title,url,content}`` list to ``{title,url,snippet}``.

    Tolerant of missing fields; drops entries with neither a title nor a url. Used by the JSON
    providers (SearXNG, Tavily) which share this result shape.
    """
    if not isinstance(results, list):
        return []
    mapped: list[dict[str, str]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("content") or item.get("snippet") or "").strip()
        if not title and not url:
            continue
        mapped.append({"title": title, "url": url, "snippet": snippet})
    return mapped[:max_results]


# --- Manifest ----------------------------------------------------------------------------------

_DESCRIPTION = (
    "General web search. Returns a list of results, each with a title, url, and snippet. "
    "Supported parameters: `query` (string, required — the search terms) and `max_results` "
    "(integer, optional — how many results to return, capped at 10). No other parameters are "
    "supported; do not pass search_depth, include_raw_content, country, or similar — they are "
    "ignored."
)

WEB_SEARCH_MANIFEST = ToolManifest(
    name="web_search",
    version="1.0.0",
    provenance=Provenance(maintainer="PersonalAI", license="Apache-2.0"),
    description=_DESCRIPTION,
    capabilities=["web.search"],
    permissions=(Permission(type=PermissionType.NETWORK, scope=DDG_HOST),),
    inputs={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search terms."},
            "max_results": {
                "type": "integer",
                "description": "How many results to return (capped at 10).",
            },
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


def web_search_manifest(host: str) -> ToolManifest:
    """Clone :data:`WEB_SEARCH_MANIFEST` with the active provider's egress ``host``.

    The gateway iterates ``manifest.egress`` and checks each host against the allowlist, so the
    egress host MUST match the provider actually contacted. The NETWORK permission scope is set to
    the same host so the grant matches by exact scope.
    """
    return WEB_SEARCH_MANIFEST.model_copy(
        update={
            "permissions": (Permission(type=PermissionType.NETWORK, scope=host),),
            "egress": (host,),
        }
    )


class WebSearch:
    """Search the web via a configurable :class:`WebSearchProvider`.

    Tolerates unknown args (e.g. the Tavily-style ``search_depth``/``country`` the model sometimes
    invents): they are ignored rather than failing the call, so the agent loop is not broken by a
    hallucinated parameter. Only ``query`` and ``max_results`` are honored.
    """

    name = "web_search"

    def __init__(self, provider: WebSearchProvider, *, max_results: int = 5) -> None:
        self._provider = provider
        self._max_results = max_results

    async def invoke(self, call: ToolCall) -> ToolResult:
        query = str(call.args.get("query", "")).strip()
        if not query:
            return ToolResult(ok=False, error="empty query")
        raw_max = call.args.get("max_results")
        limit = int(raw_max) if isinstance(raw_max, int) and raw_max > 0 else self._max_results
        limit = max(1, min(limit, _MAX_RESULTS_CAP))
        try:
            results = await self._provider.search(query, limit)
        except WebSearchError as exc:
            return ToolResult(ok=False, error=str(exc))
        except httpx.HTTPError as exc:  # defensive: a provider that didn't wrap its transport error
            return ToolResult(ok=False, error=f"search backend unreachable / blocked: {exc}")
        return ToolResult(ok=True, output={"results": results})
