"""Ollama ModelProvider adapter (ADR-0002).

Talks to a local Ollama server over its REST API (loopback by default). Implements the
``ModelProvider`` port; depends inward on ``personalai_contracts`` only (ADR-0001) and is
registered with the backend composition root. Streaming is added in M1-2, model listing in M1-4.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from types import TracebackType
from typing import Any
from urllib.parse import urlparse

import httpx

from personalai_contracts.ports.model_provider import (
    ChatMessage,
    EmbeddingResult,
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    ModelCapabilities,
    ModelDescriptor,
    ToolCallRequest,
)

DEFAULT_HOST = "http://127.0.0.1:11434"

# Egress guard: called with the target host before each request; may raise to block (wired by the
# backend to the core egress allowlist, since adapters cannot import the core — ADR-0001). Loopback
# (the default local Ollama) passes; a remote OLLAMA_HOST is blocked unless egress is allowed.
EgressGuard = Callable[[str], None]

logger = logging.getLogger(__name__)


def _context_length(model_info: Mapping[str, Any]) -> int | None:
    """Pull the context length from Ollama's architecture-keyed model_info (e.g. qwen35moe.*)."""
    for key, value in model_info.items():
        if key.endswith("context_length") and isinstance(value, int):
            return value
    return None


def _capabilities_from(caps: Sequence[str], context_length: int | None) -> ModelCapabilities:
    """Build ModelCapabilities from Ollama's capability list (from /api/show or /api/tags)."""
    present = set(caps)
    return ModelCapabilities(
        text="completion" in present,
        vision="vision" in present,
        embeddings="embedding" in present,
        tool_calling="tools" in present,
        # Ollama can constrain any completion model's output to a JSON schema.
        structured_output="completion" in present,
        thinking="thinking" in present,
        max_context_tokens=context_length,
    )


def _options(request: GenerationRequest) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if request.temperature is not None:
        options["temperature"] = request.temperature
    if request.max_tokens is not None:
        options["num_predict"] = request.max_tokens
    return options


def _strip_data_url(image: str) -> str:
    """Ollama wants raw base64; strip a ``data:...;base64,`` prefix if the UI sent a data-URL."""
    if image.startswith("data:") and "," in image:
        return image.split(",", 1)[1]
    return image


def _ollama_message(m: ChatMessage) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": m.role.value, "content": m.content}
    if m.images:
        # Ollama's chat API takes images as an array of raw base64 strings on the message (M9.1).
        msg["images"] = [_strip_data_url(img) for img in m.images]
    return msg


def _chat_payload(
    request: GenerationRequest,
    *,
    stream: bool,
    num_ctx: int | None = None,
    keep_alive: str | None = None,
) -> dict[str, Any]:
    options = _options(request)
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [_ollama_message(m) for m in request.messages],
        "stream": stream,
        "options": options,
    }
    if keep_alive is not None:
        # How long Ollama keeps the model resident after the request (e.g. "30m", "-1" = forever),
        # so a large model stays warm and the next turn skips the cold reload.
        payload["keep_alive"] = keep_alive
    if request.json_schema is not None:
        payload["format"] = dict(request.json_schema)
    if request.think is not None:
        payload["think"] = request.think
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
    """Parse Ollama ``message.tool_calls`` (arguments are already an object)."""
    calls = []
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        args = fn.get("arguments")
        calls.append(ToolCallRequest(name=name, arguments=args if isinstance(args, dict) else {}))
    return tuple(calls)


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
        self,
        base_url: str = DEFAULT_HOST,
        client: httpx.AsyncClient | None = None,
        num_ctx: int | None = None,
        keep_alive: str | None = None,
        egress_guard: EgressGuard | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._host = urlparse(self._base).hostname or self._base
        self._egress_guard = egress_guard
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        self._owns_client = client is None
        # Bound the context window (KV cache) to control memory; None leaves Ollama's default.
        self._num_ctx = num_ctx
        # Keep the model resident this long after a request (e.g. "30m", "-1"); None = default.
        self._keep_alive = keep_alive
        # Names of models Ollama proxies to the cloud (remote_host set); populated by list_models.
        # Used to warn before a request silently leaves the machine (stop-gap until M2).
        self._remote_models: set[str] = set()

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

    def _check_egress(self) -> None:
        if self._egress_guard is not None:
            self._egress_guard(self._host)

    async def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        self._check_egress()
        response = await self._client.post(f"{self._base}{path}", json=dict(payload))
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def capabilities(self, model: str) -> ModelCapabilities:
        data = await self._post("/api/show", {"model": model})
        return _capabilities_from(
            data.get("capabilities") or [], _context_length(data.get("model_info") or {})
        )

    def _warn_if_remote(self, model: str) -> None:
        if model in self._remote_models:
            logger.warning(
                "model %r is a remote/cloud model (Ollama proxies it off this machine); "
                "explicit remote-provider routing arrives in M2",
                model,
            )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self._warn_if_remote(request.model)
        data = await self._post(
            "/api/chat",
            _chat_payload(
                request, stream=False, num_ctx=self._num_ctx, keep_alive=self._keep_alive
            ),
        )
        message = data.get("message") or {}
        return GenerationResult(
            text=message.get("content", ""),
            model=data.get("model", request.model),
            finish_reason=data.get("done_reason"),
            thinking=message.get("thinking"),
            usage=_usage(data),
            tool_calls=_tool_calls(message),
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        self._check_egress()
        self._warn_if_remote(request.model)
        async with self._client.stream(
            "POST",
            f"{self._base}/api/chat",
            json=_chat_payload(
                request, stream=True, num_ctx=self._num_ctx, keep_alive=self._keep_alive
            ),
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
                    usage=_usage(data),  # token counts arrive on the final ("done") line
                    tool_calls=_tool_calls(message),  # tool calls arrive on a chunk's message
                )

    async def _get(self, path: str) -> dict[str, Any]:
        self._check_egress()
        response = await self._client.get(f"{self._base}{path}")
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def list_models(self) -> Sequence[ModelDescriptor]:
        # Ollama 0.30 returns capabilities + details.context_length and remote_host in /api/tags,
        # so we build descriptors from one call and fall back to /api/show only when a model is
        # missing context_length. remote_host marks cloud models (not local).
        data = await self._get("/api/tags")
        descriptors: list[ModelDescriptor] = []
        remote: set[str] = set()
        for entry in data.get("models") or []:
            name = entry.get("name")
            if not name:
                continue
            local = not entry.get("remote_host")
            if not local:
                remote.add(name)
            caps_list = entry.get("capabilities")
            context_length = (entry.get("details") or {}).get("context_length")
            if caps_list is not None and context_length is not None:
                capabilities = _capabilities_from(caps_list, context_length)
            else:
                capabilities = await self.capabilities(name)  # fallback: /api/show
            descriptors.append(ModelDescriptor(name=name, capabilities=capabilities, local=local))
        self._remote_models = remote
        return descriptors

    async def embed(
        self, texts: Sequence[str], model: str, *, truncate: bool = True
    ) -> EmbeddingResult:
        data = await self._post(
            "/api/embed", {"model": model, "input": list(texts), "truncate": truncate}
        )
        vectors: list[list[float]] = data.get("embeddings") or []
        dimensions = len(vectors[0]) if vectors else 0
        return EmbeddingResult(
            vectors=vectors, model=data.get("model", model), dimensions=dimensions
        )
