"""Built-in tools for PersonalAI (behind the gateway). Depends only on contracts."""

from personalai_tool_builtin.calculator import CALCULATOR_MANIFEST, Calculator
from personalai_tool_builtin.http_fetch import HTTP_FETCH_MANIFEST, EgressAllowed, HttpFetch

__all__ = [
    "CALCULATOR_MANIFEST",
    "HTTP_FETCH_MANIFEST",
    "Calculator",
    "EgressAllowed",
    "HttpFetch",
]
