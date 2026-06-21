"""Built-in tools for PersonalAI (behind the gateway). Depends only on contracts."""

from personalai_tool_builtin.calculator import CALCULATOR_MANIFEST, Calculator
from personalai_tool_builtin.http_fetch import HTTP_FETCH_MANIFEST, EgressAllowed, HttpFetch
from personalai_tool_builtin.remember import REMEMBER_MANIFEST, EmbedText, RememberTool
from personalai_tool_builtin.web_search import WEB_SEARCH_MANIFEST, WebSearch

__all__ = [
    "CALCULATOR_MANIFEST",
    "HTTP_FETCH_MANIFEST",
    "REMEMBER_MANIFEST",
    "WEB_SEARCH_MANIFEST",
    "Calculator",
    "EgressAllowed",
    "EmbedText",
    "HttpFetch",
    "RememberTool",
    "WebSearch",
]
