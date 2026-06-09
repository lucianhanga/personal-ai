"""Env-driven settings for the MarkItDown-on-Ollama MCP server (no heavy deps needed).

Loads server.py by path (it imports only `mcp` + stdlib at module level; markitdown/openai are
lazy-imported inside the tool handler), so this runs in the normal suite.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "markitdown_ollama_server", Path(__file__).resolve().parents[1] / "server.py"
)
assert _SPEC and _SPEC.loader
server = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = server  # dataclass resolution needs the module registered
_SPEC.loader.exec_module(server)


def test_defaults_point_at_local_ollama() -> None:
    s = server.settings_from_env({})
    assert s.base_url == "http://localhost:11434/v1"
    assert s.model == "qwen2.5vl:7b"
    assert s.api_key == "ollama"  # non-empty placeholder for the OpenAI client


def test_env_overrides() -> None:
    s = server.settings_from_env(
        {
            "MARKITDOWN_OLLAMA_BASE_URL": "http://gpu.local:11434/v1",
            "MARKITDOWN_OLLAMA_MODEL": "qwen2.5vl:32b",
            "OPENAI_API_KEY": "xyz",  # pragma: allowlist secret  (test placeholder, not a secret)
        }
    )
    assert s.base_url == "http://gpu.local:11434/v1"
    assert s.model == "qwen2.5vl:32b"
    assert s.api_key == "xyz"


def test_result_text_prefers_markdown_then_text_content() -> None:
    class _Md:
        markdown = "# hi"
        text_content = "ignored"

    class _Legacy:
        text_content = "plain"

    assert server._result_text(_Md()) == "# hi"
    assert server._result_text(_Legacy()) == "plain"
    assert server._result_text(object()) == ""
