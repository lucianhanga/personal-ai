"""Ollama ModelProvider adapter (ADR-0002).

Talks to a local Ollama server over its REST API (loopback by default). Implements the
``ModelProvider`` port; depends inward on ``personalai_contracts`` only (ADR-0001) and is
registered with the backend composition root. Streaming is added in M1-2, model listing in M1-4.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from types import TracebackType
from typing import Any

import httpx

from personalai_contracts.ports.model_provider import (
    EmbeddingResult,
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    ModelCapabilities,
)

DEFAULT_HOST = "http://127.0.0.1:11434"


def _context_length(model_info: Mapping[str, Any]) -> int | None:
    """Pull the context length from Ollama's architecture-keyed model_info (e.g. qwen35moe.*)."""
    for key, value in model_info.items():
        if key.endswith("context_length") and isinstance(value, int):
            return value
    return None


def _options(request: GenerationRequest) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if request.temperature is not None:
        options["temperature"] = request.temperature
    if request.max_tokens is not None:
        options["num_predict"] = request.max_tokens
    return options


def _chat_payload(request: GenerationRequest, *, stream: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
        "stream": stream,
        "options": _options(request),
    }
    if request.json_schema is not None:
        payload["format"] = dict(request.json_schema)
    if request.think is not None:
        payload["think"] = request.think
    return payload


def _usage(data: Mapping[str, Any]) -> dict[str, int]:
    usage: dict[str, int] = {}
    if isinstance(data.get("prompt_eval_count"), int):
        usage["prompt_tokens"] = data["prompt_eval_count"]
    if isinstance(data.get("eval_count"), int):
        usage["completion_tokens"] = data["eval_count"]
    return usage


class OllamaProvider:
    """A :class:`ModelProvider` backed by a local Ollama server."""

    name = "ollama"

    def __init__(
        self, base_url: str = DEFAULT_HOST, client: httpx.AsyncClient | None = None
    ) -> None:
        self._base = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> OllamaProvider:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        response = await self._client.post(f"{self._base}{path}", json=dict(payload))
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def capabilities(self, model: str) -> ModelCapabilities:
        data = await self._post("/api/show", {"model": model})
        caps = set(data.get("capabilities") or [])
        return ModelCapabilities(
            text="completion" in caps,
            vision="vision" in caps,
            embeddings="embedding" in caps,
            tool_calling="tools" in caps,
            # Ollama can constrain any completion model's output to a JSON schema.
            structured_output="completion" in caps,
            thinking="thinking" in caps,
            max_context_tokens=_context_length(data.get("model_info") or {}),
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        data = await self._post("/api/chat", _chat_payload(request, stream=False))
        message = data.get("message") or {}
        return GenerationResult(
            text=message.get("content", ""),
            model=data.get("model", request.model),
            finish_reason=data.get("done_reason"),
            thinking=message.get("thinking"),
            usage=_usage(data),
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        async with self._client.stream(
            "POST", f"{self._base}/api/chat", json=_chat_payload(request, stream=True)
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                message = data.get("message") or {}
                yield GenerationChunk(
                    delta=message.get("content", ""),
                    thinking=message.get("thinking"),
                    done=bool(data.get("done")),
                    finish_reason=data.get("done_reason"),
                )

    async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
        data = await self._post("/api/embed", {"model": model, "input": list(texts)})
        vectors: list[list[float]] = data.get("embeddings") or []
        dimensions = len(vectors[0]) if vectors else 0
        return EmbeddingResult(
            vectors=vectors, model=data.get("model", model), dimensions=dimensions
        )
