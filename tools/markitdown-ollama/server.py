# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=1.0", "markitdown[all]>=0.1", "openai>=1.0"]
# ///
"""MarkItDown-on-Ollama MCP server (stdio).

A small first-party MCP server that converts files/URLs to Markdown with **local** image
descriptions/OCR via an Ollama vision model — instead of a remote OpenAI service. The official
``markitdown-mcp`` does plain conversion only (it never wires an LLM client), so this fills the gap.

It exposes one tool, ``convert_to_markdown(uri)`` (``file:``/``http:``/``https:``/``data:``), and
points MarkItDown's image converter at Ollama's OpenAI-compatible endpoint.

Run it standalone (uv resolves the deps from the inline metadata above):

    uv run --script tools/markitdown-ollama/server.py

Configure from PersonalAI via mcp.json (see docs/guides/mcp.md):

    "markitdown": {
      "command": "uv",
      "args": ["run", "--script", "/ABS/PATH/tools/markitdown-ollama/server.py"],
      "env": { "MARKITDOWN_OLLAMA_MODEL": "qwen2.5vl:7b" }
    }

Environment:
- MARKITDOWN_OLLAMA_BASE_URL  (default http://localhost:11434/v1) — Ollama OpenAI endpoint
- MARKITDOWN_OLLAMA_MODEL     (default qwen2.5vl:7b)               — a vision model in Ollama
- OPENAI_API_KEY              (default "ollama")                   — ignored by Ollama; non-empty
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from mcp.server.fastmcp import FastMCP

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5vl:7b"


@dataclass(frozen=True)
class Settings:
    """Where to reach the local vision model."""

    base_url: str
    model: str
    api_key: str


def settings_from_env(env: Mapping[str, str]) -> Settings:
    """Resolve the Ollama vision settings from environment variables (with safe defaults)."""
    return Settings(
        base_url=env.get("MARKITDOWN_OLLAMA_BASE_URL") or DEFAULT_BASE_URL,
        model=env.get("MARKITDOWN_OLLAMA_MODEL") or DEFAULT_MODEL,
        # Ollama ignores the key but the OpenAI client requires a non-empty value.
        api_key=env.get("OPENAI_API_KEY") or "ollama",
    )


mcp = FastMCP("markitdown-ollama")


def _build_markitdown(settings: Settings):  # type: ignore[no-untyped-def]
    """Construct a MarkItDown that captions images via the local Ollama vision model."""
    from markitdown import MarkItDown  # lazy: heavy dep, only needed when converting
    from openai import OpenAI

    client = OpenAI(base_url=settings.base_url, api_key=settings.api_key)
    return MarkItDown(llm_client=client, llm_model=settings.model)


def _result_text(result: object) -> str:
    """Extract Markdown text from a MarkItDown result across library versions."""
    return str(getattr(result, "markdown", None) or getattr(result, "text_content", "") or "")


@mcp.tool()
def convert_to_markdown(uri: str) -> str:
    """Convert a document to Markdown, describing images with a local Ollama vision model.

    ``uri`` may be a local path, ``file://``, ``http(s)://`` or ``data:`` URI. Supports PDF, DOCX,
    PPTX, XLSX, HTML, images, and more.
    """
    settings = settings_from_env(os.environ)
    md = _build_markitdown(settings)
    parsed = urlparse(uri)
    source = unquote(parsed.path) if parsed.scheme in ("", "file") else uri
    return _result_text(md.convert(source))


if __name__ == "__main__":
    mcp.run()
