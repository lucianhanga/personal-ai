"""OpenAI-compatible ModelProvider adapter (ADR-0002).

Speaks the OpenAI Chat Completions API, so it works with OpenAI, Azure OpenAI, and the many
runtimes that expose an OpenAI-compatible endpoint (Together, Groq, OpenRouter, local vLLM, ...).

This is a **remote** provider: every network call first runs an injected ``egress_guard`` (wired
by the backend to the egress allowlist, since adapters cannot import the core — ADR-0001). The API
key is injected, never hard-coded, and never logged.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from types import TracebackType
from typing import Any
from urllib.parse import urlparse

import httpx

from personalai_contracts.ports.model_provider import (
    EmbeddingResult,
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    ModelCapabilities,
    ModelDescriptor,
    ToolCallRequest,
)

DEFAULT_BASE_URL = "https://api.openai.com/v1"

# Egress guard: called with the target host before each request; may raise to block.
EgressGuard = Callable[[str], None]


def _messages(request: GenerationRequest) -> list[dict[str, Any]]:
    return [{"role": m.role.value, "content": m.content} for m in request.messages]


def _chat_payload(request: GenerationRequest, *, stream: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": _messages(request),
        "stream": stream,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.json_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "output", "schema": dict(request.json_schema), "strict": True},
        }
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": dict(t.parameters),
                },
            }
            for t in request.tools
        ]
    return payload


def _tool_calls(message: Mapping[str, Any]) -> tuple[ToolCallRequest, ...]:
    """Parse OpenAI ``message.tool_calls`` (arguments is a JSON string)."""
    calls = []
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except (ValueError, TypeError):
            args = {}
        calls.append(
            ToolCallRequest(
                name=name, arguments=args if isinstance(args, dict) else {}, id=call.get("id")
            )
        )
    return tuple(calls)


def _remote_capabilities() -> ModelCapabilities:
    # Remote OpenAI-compatible APIs do not expose a capability endpoint; assume the common set.
    return ModelCapabilities(
        text=True, tool_calling=True, structured_output=True, max_context_tokens=None
    )


class OpenAICompatProvider:
    """A :class:`ModelProvider` backed by an OpenAI-compatible HTTP API (remote)."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        *,
        client: httpx.AsyncClient | None = None,
        egress_guard: EgressGuard | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._host = urlparse(self._base).hostname or ""
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        self._owns_client = client is None
        self._egress_guard = egress_guard

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> OpenAICompatProvider:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def _check_egress(self) -> None:
        if self._egress_guard is not None:
            self._egress_guard(self._host)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    async def capabilities(self, model: str) -> ModelCapabilities:
        return _remote_capabilities()

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self._check_egress()
        response = await self._client.post(
            f"{self._base}/chat/completions",
            headers=self._headers(),
            json=_chat_payload(request, stream=False),
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage_raw = data.get("usage") or {}
        usage = {
            k: usage_raw[k]
            for k in ("prompt_tokens", "completion_tokens")
            if isinstance(usage_raw.get(k), int)
        }
        return GenerationResult(
            text=message.get("content") or "",
            model=data.get("model", request.model),
            finish_reason=choice.get("finish_reason"),
            usage=usage,
            tool_calls=_tool_calls(message),
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        self._check_egress()
        async with self._client.stream(
            "POST",
            f"{self._base}/chat/completions",
            headers=self._headers(),
            json=_chat_payload(request, stream=True),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if payload == "[DONE]":
                    yield GenerationChunk(done=True)
                    break
                data = json.loads(payload)
                choice = (data.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                yield GenerationChunk(
                    delta=delta.get("content") or "",
                    finish_reason=choice.get("finish_reason"),
                )

    async def list_models(self) -> Sequence[ModelDescriptor]:
        self._check_egress()
        response = await self._client.get(f"{self._base}/models", headers=self._headers())
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        caps = _remote_capabilities()
        return [
            ModelDescriptor(name=entry["id"], capabilities=caps, local=False)
            for entry in data.get("data") or []
            if entry.get("id")
        ]

    async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
        self._check_egress()
        response = await self._client.post(
            f"{self._base}/embeddings",
            headers=self._headers(),
            json={"model": model, "input": list(texts)},
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        vectors: list[list[float]] = [row["embedding"] for row in data.get("data") or []]
        dimensions = len(vectors[0]) if vectors else 0
        return EmbeddingResult(
            vectors=vectors, model=data.get("model", model), dimensions=dimensions
        )
