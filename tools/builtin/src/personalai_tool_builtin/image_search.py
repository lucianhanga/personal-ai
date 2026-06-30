"""An image-search tool with a swappable search-provider abstraction.

This exists because LLMs cannot reliably emit image URLs from memory: a Wikimedia thumbnail URL,
for example, embeds the MD5 hash of the filename in its path and only serves a fixed set of
thumbnail widths, so a hand-built URL is almost always wrong (404/400) and never renders. The fix
is to give the model a real lookup: it calls ``image_search`` with a query and gets back genuine,
directly-fetchable ``image_url`` values that the app then localizes and displays.

The tool delegates to a swappable :class:`ImageSearchProvider`. The default provider queries the
Wikimedia Commons API (no API key, encyclopedic coverage), which resolves the correct path hash AND
a standard thumbnail width so the returned URL is guaranteed servable. Each provider exposes the
egress ``host`` the gateway must allow; the composition root builds the manifest's ``egress`` from
the active provider's host.

No extra dependency: every adapter uses httpx (already a dep). MEDIUM risk (read-only network).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx

from personalai_contracts.ports import ToolCall, ToolResult
from personalai_contracts.schemas.tools import (
    Permission,
    PermissionType,
    Provenance,
    RiskLevel,
    ToolManifest,
)

WIKIMEDIA_COMMONS_HOST = "commons.wikimedia.org"

# Hard cap on results regardless of what the caller asks for (bounds payload + provider cost).
_MAX_RESULTS_CAP = 10

# Wikimedia only serves a FIXED set of thumbnail widths for direct (hotlink) requests; a
# non-standard width is rejected with HTTP 400. 500 is one of the standard widths
# (20, 40, 60, 120, 250, 330, 500, 960, 1280, 1920, 3840) and a sensible inline-display size.
_COMMONS_THUMB_WIDTH = 500


@runtime_checkable
class ImageSearchProvider(Protocol):
    """A swappable image-search backend.

    ``search`` returns a list of ``{"title", "image_url", "page_url", "width", "height"}`` dicts
    (possibly empty — "no results" is a success, not an error). Every ``image_url`` MUST be a real,
    directly-fetchable raster-image URL. ``host`` is the egress host the gateway must allow for this
    provider; ``name`` is a short human label used in logs/diagnostics.
    """

    name: str

    @property
    def host(self) -> str:
        """The egress host the gateway must allow when this provider is active."""
        ...

    async def search(self, query: str, max_results: int) -> list[dict[str, object]]:
        """Run the search and return mapped results. Raises on transport/HTTP/protocol errors."""
        ...


class ImageSearchError(RuntimeError):
    """A clear, provider-agnostic image-search failure (transport, HTTP status, or bad payload)."""


def _clean_title(raw: str) -> str:
    """Turn a Commons page title (``File:44 Bill Clinton 3x4.jpg``) into readable alt text."""
    title = raw.split(":", 1)[1] if raw.lower().startswith("file:") else raw
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".tiff", ".tif"):
        if title.lower().endswith(ext):
            title = title[: -len(ext)]
            break
    return title.strip()


# --- Wikimedia Commons (no API key, encyclopedic) ----------------------------------------------


class WikimediaCommonsImageSearch:
    """Search Wikimedia Commons for images via its MediaWiki API.

    Uses ``action=query&generator=search`` over the File namespace with ``prop=imageinfo`` so each
    hit carries an ``imageinfo`` block. Requesting ``iiurlwidth`` makes the API return a
    ``thumburl`` at a server-rendered standard width — the correct, fetchable URL (the model cannot
    construct this itself because the path hash is the MD5 of the filename). Non-image media
    (audio/video/PDF) are dropped so only raster-displayable results are returned.
    """

    name = "wikimedia"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
        thumb_width: int = _COMMONS_THUMB_WIDTH,
        user_agent: str = "PersonalAI/1.0 (+https://github.com/lucianhanga/personal-ai)",
    ) -> None:
        self._client = client
        self._timeout = timeout
        self._thumb_width = thumb_width
        self._user_agent = user_agent

    @property
    def host(self) -> str:
        return WIKIMEDIA_COMMONS_HOST

    async def search(self, query: str, max_results: int) -> list[dict[str, object]]:
        client = self._client or httpx.AsyncClient(timeout=self._timeout, follow_redirects=False)
        try:
            params = {
                "action": "query",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": "6",  # the File: namespace
                "gsrlimit": str(max_results),
                "prop": "imageinfo",
                "iiprop": "url|size|mime",
                "iiurlwidth": str(self._thumb_width),
                "format": "json",
                "formatversion": "2",
            }
            try:
                response = await client.get(
                    f"https://{WIKIMEDIA_COMMONS_HOST}/w/api.php",
                    params=params,
                    headers={"User-Agent": self._user_agent},
                )
            except httpx.HTTPError as exc:
                raise ImageSearchError(f"image search unreachable / blocked: {exc}") from exc
            if response.status_code >= 400:
                raise ImageSearchError(
                    f"image search returned HTTP {response.status_code} from {self.host}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise ImageSearchError(f"image search returned non-JSON response: {exc}") from exc
            return _map_commons_pages(payload, max_results)
        finally:
            if self._client is None:
                await client.aclose()


def _map_commons_pages(payload: object, max_results: int) -> list[dict[str, object]]:
    """Map a Commons ``query.pages`` list to ``{title,image_url,page_url,width,height}`` results.

    Drops anything without a raster thumbnail (non-image media, or a hit the API could not render),
    and orders by the search ``index`` so the most relevant hit comes first.
    """
    pages = payload.get("query", {}).get("pages") if isinstance(payload, dict) else None
    if not isinstance(pages, list):
        return []
    pages = sorted(pages, key=lambda p: p.get("index", 1_000_000) if isinstance(p, dict) else 0)
    mapped: list[dict[str, object]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        info = page.get("imageinfo")
        if not isinstance(info, list) or not info or not isinstance(info[0], dict):
            continue
        ii = info[0]
        thumb = ii.get("thumburl")
        mime = str(ii.get("mime") or "")
        # Require a thumbnail and an image MIME — the app can only localize raster images. (An SVG's
        # thumburl is itself a server-rendered PNG, so it qualifies and renders fine.)
        if not thumb or not mime.startswith("image/"):
            continue
        mapped.append(
            {
                "title": _clean_title(str(page.get("title") or "")),
                "image_url": str(thumb),
                "page_url": str(ii.get("descriptionurl") or ""),
                "width": int(ii.get("thumbwidth") or 0),
                "height": int(ii.get("thumbheight") or 0),
            }
        )
    return mapped[:max_results]


# --- Manifest ----------------------------------------------------------------------------------

_DESCRIPTION = (
    "Search for real, displayable images. Returns a list of results, each with a `title`, an "
    "`image_url` (a real, directly-fetchable image you can show inline), a `page_url`, and pixel "
    "`width`/`height`. Use this WHENEVER you want to display an image: never write or guess an "
    "image URL yourself — hand-built image URLs are almost always wrong and fail to load. "
    "Parameters: `query` (string, required — what to find, e.g. 'Bill Clinton portrait') and "
    "`max_results` (integer, optional — capped at 10)."
)

IMAGE_SEARCH_MANIFEST = ToolManifest(
    name="image_search",
    version="1.0.0",
    provenance=Provenance(maintainer="PersonalAI", license="Apache-2.0"),
    description=_DESCRIPTION,
    capabilities=["image.search"],
    permissions=(Permission(type=PermissionType.NETWORK, scope=WIKIMEDIA_COMMONS_HOST),),
    inputs={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What image to find."},
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
                        "image_url": {"type": "string"},
                        "page_url": {"type": "string"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                },
            }
        },
        "required": ["results"],
    },
    egress=(WIKIMEDIA_COMMONS_HOST,),
    risk=RiskLevel.MEDIUM,
)


def image_search_manifest(host: str) -> ToolManifest:
    """Clone :data:`IMAGE_SEARCH_MANIFEST` with the active provider's egress ``host``.

    The gateway iterates ``manifest.egress`` and checks each host against the allowlist, so the
    egress host MUST match the provider actually contacted. The NETWORK permission scope is set to
    the same host so the grant matches by exact scope.
    """
    return IMAGE_SEARCH_MANIFEST.model_copy(
        update={
            "permissions": (Permission(type=PermissionType.NETWORK, scope=host),),
            "egress": (host,),
        }
    )


class ImageSearch:
    """Search for images via a configurable :class:`ImageSearchProvider`.

    Tolerates unknown args (the model sometimes invents extra parameters): they are ignored rather
    than failing the call. Only ``query`` and ``max_results`` are honored.
    """

    name = "image_search"

    def __init__(self, provider: ImageSearchProvider, *, max_results: int = 5) -> None:
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
        except ImageSearchError as exc:
            return ToolResult(ok=False, error=str(exc))
        except httpx.HTTPError as exc:  # defensive: a provider that didn't wrap its transport error
            return ToolResult(ok=False, error=f"image search unreachable / blocked: {exc}")
        return ToolResult(ok=True, output={"results": results})
