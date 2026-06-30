"""image_search tool: the Wikimedia Commons provider's mapping (real fetchable image_url, relevance
ordering, non-image filtering), the tool's tolerance of unknown args, empty-result and empty-query
handling, and clear error surfacing. httpx-mocked."""

from __future__ import annotations

import asyncio

import httpx
import respx

from personalai_contracts.ports import ToolCall, ToolResult
from personalai_tool_builtin import (
    ImageSearch,
    WikimediaCommonsImageSearch,
    image_search_manifest,
)
from personalai_tool_builtin.image_search import WIKIMEDIA_COMMONS_HOST

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
