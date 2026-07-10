"""image_search tool: the Wikimedia Commons provider's mapping (real fetchable image_url, relevance
ordering, non-image filtering), the tool's tolerance of unknown args, empty-result and empty-query
handling, and clear error surfacing. httpx-mocked."""

from __future__ import annotations

import asyncio

import httpx
import respx

from personalai_contracts.ports import ToolCall, ToolResult
from personalai_tool_builtin import (
    FallbackImageSearch,
    ImageSearch,
    TavilyImageSearch,
    WikimediaCommonsImageSearch,
    image_search_manifest,
)
from personalai_tool_builtin.image_search import TAVILY_HOST, WIKIMEDIA_COMMONS_HOST

_API = f"https://{WIKIMEDIA_COMMONS_HOST}/w/api.php"

# A Commons action=query&generator=search response (formatversion=2). Pages arrive out of relevance
# order (index 2 before 1); the mapper must sort by index. The third hit is an audio file with no
# thumbnail and a non-image MIME — it must be dropped.
_COMMONS_JSON = {
    "query": {
        "pages": [
            {
                "index": 2,
                "title": "File:Lemon - second.jpg",
                "imageinfo": [
                    {
                        "mime": "image/jpeg",
                        "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/b/bb/Lemon_second.jpg/500px-Lemon_second.jpg",
                        "thumbwidth": 500,
                        "thumbheight": 333,
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Lemon_second.jpg",
                    }
                ],
            },
            {
                "index": 1,
                "title": "File:Lemon fruit.jpg",
                "imageinfo": [
                    {
                        "mime": "image/jpeg",
                        "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/cf/Lemon_fruit.jpg/500px-Lemon_fruit.jpg",
                        "thumbwidth": 500,
                        "thumbheight": 281,
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Lemon_fruit.jpg",
                    }
                ],
            },
            {
                "index": 3,
                "title": "File:Lemon squeeze sound.ogg",
                "imageinfo": [
                    {"mime": "application/ogg", "descriptionurl": "https://commons.wikimedia.org/x"}
                ],
            },
        ]
    }
}


def _search(handler: ImageSearch, query: str, **args: object) -> ToolResult:
    return asyncio.run(handler.invoke(ToolCall("image_search", "1.0.0", {"query": query, **args})))


@respx.mock
def test_commons_maps_pages_orders_by_index_and_drops_non_images() -> None:
    respx.get(_API).mock(return_value=httpx.Response(200, json=_COMMONS_JSON))
    result = _search(ImageSearch(WikimediaCommonsImageSearch()), "lemon")
    assert result.ok
    results = result.output["results"]
    # the .ogg is dropped; the two images are sorted by search index (1 before 2)
    assert len(results) == 2
    assert results[0] == {
        "title": "Lemon fruit",
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/cf/Lemon_fruit.jpg/500px-Lemon_fruit.jpg",
        "page_url": "https://commons.wikimedia.org/wiki/File:Lemon_fruit.jpg",
        "width": 500,
        "height": 281,
    }
    assert results[1]["title"] == "Lemon - second"


@respx.mock
def test_commons_respects_max_results() -> None:
    respx.get(_API).mock(return_value=httpx.Response(200, json=_COMMONS_JSON))
    result = _search(ImageSearch(WikimediaCommonsImageSearch()), "lemon", max_results=1)
    assert len(result.output["results"]) == 1
    assert result.output["results"][0]["title"] == "Lemon fruit"


@respx.mock
def test_commons_empty_results_is_ok() -> None:
    respx.get(_API).mock(return_value=httpx.Response(200, json={"query": {"pages": []}}))
    result = _search(ImageSearch(WikimediaCommonsImageSearch()), "nothingmatcheszzz")
    assert result.ok and result.output["results"] == []


def test_commons_host() -> None:
    assert WikimediaCommonsImageSearch().host == WIKIMEDIA_COMMONS_HOST


@respx.mock
def test_unknown_args_are_tolerated_and_search_still_runs() -> None:
    respx.get(_API).mock(return_value=httpx.Response(200, json=_COMMONS_JSON))
    result = _search(
        ImageSearch(WikimediaCommonsImageSearch()), "lemon", license="cc0", color="yellow"
    )
    assert result.ok and len(result.output["results"]) == 2


def test_empty_query_rejected() -> None:
    result = _search(ImageSearch(WikimediaCommonsImageSearch()), "   ")
    assert not result.ok and "empty query" in (result.error or "")


@respx.mock
def test_transport_error_is_clear_and_fail_closed() -> None:
    respx.get(_API).mock(side_effect=httpx.ConnectError("down"))
    result = _search(ImageSearch(WikimediaCommonsImageSearch()), "lemon")
    assert not result.ok
    assert "unreachable" in (result.error or "")


@respx.mock
def test_http_status_error_includes_status() -> None:
    respx.get(_API).mock(return_value=httpx.Response(429, json={}))
    result = _search(ImageSearch(WikimediaCommonsImageSearch()), "lemon")
    assert not result.ok and "429" in (result.error or "")


def test_manifest_egress_matches_active_provider_host() -> None:
    manifest = image_search_manifest(WikimediaCommonsImageSearch().host)
    assert manifest.egress == (WIKIMEDIA_COMMONS_HOST,)
    assert manifest.permissions[0].scope == WIKIMEDIA_COMMONS_HOST


def test_manifest_supports_multiple_egress_hosts() -> None:
    # A Wikimedia+Tavily fallback contacts both backends, so both hosts must be allow-gated.
    manifest = image_search_manifest(WIKIMEDIA_COMMONS_HOST, TAVILY_HOST)
    assert manifest.egress == (WIKIMEDIA_COMMONS_HOST, TAVILY_HOST)
    assert {p.scope for p in manifest.permissions} == {WIKIMEDIA_COMMONS_HOST, TAVILY_HOST}


_TAVILY_API = f"https://{TAVILY_HOST}/search"


@respx.mock
def test_tavily_maps_image_results_with_descriptions() -> None:
    respx.post(_TAVILY_API).mock(
        return_value=httpx.Response(
            200,
            json={
                "images": [
                    {"url": "https://example.com/ceo.jpg", "description": "Philipp Göllner, CEO"},
                    {"url": "https://example.org/team.png", "description": "team photo"},
                    {"url": "ftp://bad/scheme.jpg", "description": "dropped (not http)"},
                ]
            },
        )
    )
    result = _search(ImageSearch(TavilyImageSearch("k")), "Philipp Göllner")
    assert result.ok
    rows = result.output["results"]
    assert [r["image_url"] for r in rows] == [
        "https://example.com/ceo.jpg",
        "https://example.org/team.png",
    ]
    assert rows[0]["title"] == "Philipp Göllner, CEO"


@respx.mock
def test_tavily_maps_plain_url_images_using_query_as_title() -> None:
    respx.post(_TAVILY_API).mock(
        return_value=httpx.Response(200, json={"images": ["https://example.com/a.jpg"]})
    )
    result = _search(ImageSearch(TavilyImageSearch("k")), "a lemon")
    assert result.ok
    assert result.output["results"] == [
        {
            "title": "a lemon",
            "image_url": "https://example.com/a.jpg",
            "page_url": "",
            "width": 0,
            "height": 0,
        }
    ]


class _FakeProvider:
    name = "fake"

    def __init__(self, host: str, results: list[dict[str, object]]) -> None:
        self._host = host
        self._results = results
        self.calls = 0

    @property
    def host(self) -> str:
        return self._host

    @property
    def egress_hosts(self) -> tuple[str, ...]:
        return (self._host,)

    async def search(self, query: str, max_results: int) -> list[dict[str, object]]:
        self.calls += 1
        return list(self._results)


def test_fallback_uses_primary_when_it_has_results() -> None:
    primary = _FakeProvider("primary.example", [{"image_url": "p"}])
    fallback = _FakeProvider("fallback.example", [{"image_url": "f"}])
    result = _search(ImageSearch(FallbackImageSearch(primary, fallback)), "x")
    assert [r["image_url"] for r in result.output["results"]] == ["p"]
    assert fallback.calls == 0  # primary had results -> fallback never queried


def test_fallback_falls_back_when_primary_is_empty() -> None:
    primary = _FakeProvider("primary.example", [])
    fallback = _FakeProvider("fallback.example", [{"image_url": "f"}])
    result = _search(ImageSearch(FallbackImageSearch(primary, fallback)), "x")
    assert [r["image_url"] for r in result.output["results"]] == ["f"]
    assert primary.calls == 1 and fallback.calls == 1


def test_fallback_egress_hosts_union_both_backends() -> None:
    composite = FallbackImageSearch(WikimediaCommonsImageSearch(), TavilyImageSearch("k"))
    assert composite.egress_hosts == (WIKIMEDIA_COMMONS_HOST, TAVILY_HOST)
