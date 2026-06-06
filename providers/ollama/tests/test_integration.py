"""Opt-in integration tests against a REAL local Ollama server.

Skipped by default (and in CI). Run locally with a live Ollama:

    PERSONALAI_OLLAMA_IT=1 uv run pytest providers/ollama/tests/test_integration.py -q

Override the models with PERSONALAI_IT_MODEL (chat) and PERSONALAI_IT_EMBED (embeddings).
The chat model defaults to a fast, non-thinking model so the test is quick.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from personalai_contracts.ports import ChatMessage, GenerationRequest, Role
from personalai_provider_ollama import OllamaProvider

pytestmark = pytest.mark.skipif(
    os.environ.get("PERSONALAI_OLLAMA_IT") != "1",
    reason="set PERSONALAI_OLLAMA_IT=1 to run integration tests against a live Ollama",
)

CHAT_MODEL = os.environ.get("PERSONALAI_IT_MODEL", "gemma3:latest")
EMBED_MODEL = os.environ.get("PERSONALAI_IT_EMBED", "mxbai-embed-large")


def test_list_models_returns_local_models() -> None:
    async def _run() -> None:
        provider = OllamaProvider()
        try:
            models = await provider.list_models()
            assert len(models) > 0
            assert all(m.local for m in models)
        finally:
            await provider.aclose()

    asyncio.run(_run())


def test_capabilities_for_chat_model() -> None:
    async def _run() -> None:
        provider = OllamaProvider()
        try:
            caps = await provider.capabilities(CHAT_MODEL)
            assert caps.text is True
        finally:
            await provider.aclose()

    asyncio.run(_run())


def test_generate_returns_text() -> None:
    async def _run() -> None:
        provider = OllamaProvider()
        req = GenerationRequest(
            messages=[ChatMessage(Role.USER, "Reply with a short greeting.")],
            model=CHAT_MODEL,
            think=False,
        )
        try:
            result = await provider.generate(req)
            assert result.text.strip() != ""
        finally:
            await provider.aclose()

    asyncio.run(_run())


def test_stream_yields_text() -> None:
    async def _run() -> None:
        provider = OllamaProvider()
        req = GenerationRequest(
            messages=[ChatMessage(Role.USER, "Count to three.")], model=CHAT_MODEL, think=False
        )
        try:
            text = "".join([chunk.delta async for chunk in provider.stream(req)])
            assert text.strip() != ""
        finally:
            await provider.aclose()

    asyncio.run(_run())


def test_embed_returns_vectors() -> None:
    async def _run() -> None:
        provider = OllamaProvider()
        try:
            result = await provider.embed(["hello"], EMBED_MODEL)
            assert result.dimensions > 0
            assert len(result.vectors) == 1
        finally:
            await provider.aclose()

    asyncio.run(_run())
