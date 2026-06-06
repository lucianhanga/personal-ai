"""Opt-in integration tests against a REAL OpenAI-compatible API.

Skipped by default (and in CI). Run locally with a key:

    PERSONALAI_OPENAI_IT=1 PERSONALAI_OPENAI_API_KEY=sk-... \
        uv run pytest providers/openai_compat/tests/test_integration.py -q

Override with PERSONALAI_OPENAI_BASE_URL, PERSONALAI_OPENAI_IT_MODEL (chat),
PERSONALAI_OPENAI_IT_EMBED (embeddings). Defaults target OpenAI's cheap models.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from personalai_contracts.ports import ChatMessage, GenerationRequest, Role
from personalai_provider_openai import OpenAICompatProvider

pytestmark = pytest.mark.skipif(
    os.environ.get("PERSONALAI_OPENAI_IT") != "1",
    reason="set PERSONALAI_OPENAI_IT=1 (+ PERSONALAI_OPENAI_API_KEY) to run remote integration",
)

API_KEY = os.environ.get("PERSONALAI_OPENAI_API_KEY", "")
BASE_URL = os.environ.get("PERSONALAI_OPENAI_BASE_URL", "https://api.openai.com/v1")
CHAT_MODEL = os.environ.get("PERSONALAI_OPENAI_IT_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.environ.get("PERSONALAI_OPENAI_IT_EMBED", "text-embedding-3-small")


def _provider() -> OpenAICompatProvider:
    return OpenAICompatProvider(api_key=API_KEY, base_url=BASE_URL)


def test_list_models_returns_remote_models() -> None:
    async def _run() -> None:
        provider = _provider()
        try:
            models = await provider.list_models()
            assert len(models) > 0
            assert all(m.local is False for m in models)
        finally:
            await provider.aclose()

    asyncio.run(_run())


def test_generate_returns_text() -> None:
    async def _run() -> None:
        provider = _provider()
        req = GenerationRequest(
            messages=[ChatMessage(Role.USER, "Reply with exactly: OK")],
            model=CHAT_MODEL,
            max_tokens=5,
        )
        try:
            result = await provider.generate(req)
            assert result.text.strip() != ""
        finally:
            await provider.aclose()

    asyncio.run(_run())


def test_stream_yields_text() -> None:
    async def _run() -> None:
        provider = _provider()
        req = GenerationRequest(
            messages=[ChatMessage(Role.USER, "Count to three.")], model=CHAT_MODEL, max_tokens=20
        )
        try:
            text = "".join([chunk.delta async for chunk in provider.stream(req)])
            assert text.strip() != ""
        finally:
            await provider.aclose()

    asyncio.run(_run())


def test_embed_returns_vectors() -> None:
    async def _run() -> None:
        provider = _provider()
        try:
            result = await provider.embed(["hello"], EMBED_MODEL)
            assert result.dimensions > 0
            assert len(result.vectors) == 1
        finally:
            await provider.aclose()

    asyncio.run(_run())
