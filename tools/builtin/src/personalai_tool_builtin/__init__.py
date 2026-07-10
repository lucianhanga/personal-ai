"""Built-in tools for PersonalAI (behind the gateway). Depends only on contracts."""

from personalai_tool_builtin.calculator import CALCULATOR_MANIFEST, Calculator
from personalai_tool_builtin.http_fetch import HTTP_FETCH_MANIFEST, EgressAllowed, HttpFetch
from personalai_tool_builtin.image_search import (
    IMAGE_SEARCH_MANIFEST,
    FallbackImageSearch,
    ImageSearch,
    ImageSearchProvider,
    TavilyImageSearch,
    WikimediaCommonsImageSearch,
    image_search_manifest,
)
from personalai_tool_builtin.memory_edit import (
    FORGET_MEMORY_MANIFEST,
    UPDATE_MEMORY_MANIFEST,
    EmbedText,
    ForgetMemoryTool,
    UpdateMemoryTool,
)
from personalai_tool_builtin.remember import REMEMBER_MANIFEST, RememberTool, SaveMemory
from personalai_tool_builtin.web_search import (
    WEB_SEARCH_MANIFEST,
    DuckDuckGoSearch,
    SearxngSearch,
    TavilySearch,
    WebSearch,
    WebSearchProvider,
    web_search_manifest,
)

__all__ = [
    "CALCULATOR_MANIFEST",
    "FORGET_MEMORY_MANIFEST",
    "HTTP_FETCH_MANIFEST",
    "IMAGE_SEARCH_MANIFEST",
    "REMEMBER_MANIFEST",
    "UPDATE_MEMORY_MANIFEST",
    "WEB_SEARCH_MANIFEST",
    "Calculator",
    "DuckDuckGoSearch",
    "EgressAllowed",
    "EmbedText",
    "ForgetMemoryTool",
    "HttpFetch",
    "FallbackImageSearch",
    "ImageSearch",
    "ImageSearchProvider",
    "TavilyImageSearch",
    "RememberTool",
    "SaveMemory",
    "SearxngSearch",
    "TavilySearch",
    "UpdateMemoryTool",
    "WebSearch",
    "WebSearchProvider",
    "WikimediaCommonsImageSearch",
    "image_search_manifest",
    "web_search_manifest",
]
