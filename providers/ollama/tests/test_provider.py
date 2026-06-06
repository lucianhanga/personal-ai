"""OllamaProvider against a mocked Ollama REST API (respx) — no live server needed."""

from __future__ import annotations

import asyncio
import json as _json
import logging
from collections.abc import Awaitable, Callable

import httpx
import pytest
import respx

from personalai_contracts.ports import ChatMessage, GenerationRequest, ModelProvider, Role
from personalai_provider_ollama import OllamaProvider

BASE = "http://127.0.0.1:11434"


def run[T](call: Callable[[OllamaProvider], Awaitable[T]]) -> T:
    async def _inner() -> T:
        provider = OllamaProvider(base_url=BASE)
        try:
            return await call(provider)
        finally:
            await provider.aclose()

    return asyncio.run(_inner())


def test_is_a_model_provider() -> None:
    assert isinstance(OllamaProvider(base_url=BASE), ModelProvider)


@respx.mock
def test_capabilities_detects_vision_tools_and_context() -> None:
    respx.post(f"{BASE}/api/show").mock(
        return_value=httpx.Response(
            200,
            json={
                "capabilities": ["completion", "vision", "tools", "thinking"],
                "model_info": {"qwen35moe.context_length": 262144},
            },
        )
    )
    caps = run(lambda p: p.capabilities("qwen3.6:35b-a3b"))
    assert caps.text is True
    assert caps.vision is True
    assert caps.tool_calling is True
    assert caps.structured_output is True
    assert caps.max_context_tokens == 262144


@respx.mock
def test_capabilities_embedding_model() -> None:
    respx.post(f"{BASE}/api/show").mock(
        return_value=httpx.Response(
            200,
            json={"capabilities": ["embedding"], "model_info": {"general.architecture": "bert"}},
        )
    )
    caps = run(lambda p: p.capabilities("mxbai-embed-large"))
    assert caps.embeddings is True
    assert caps.text is False
    assert caps.max_context_tokens is None


@respx.mock
def test_generate_maps_response_and_passes_schema() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "qwen3:8b",
                "message": {"role": "assistant", "content": "hello there"},
                "done_reason": "stop",
                "prompt_eval_count": 7,
                "eval_count": 3,
            },
        )
    )
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    req = GenerationRequest(
        messages=[ChatMessage(Role.USER, "hi")], model="qwen3:8b", json_schema=schema
    )
    result = run(lambda p: p.generate(req))
    assert result.text == "hello there"
    assert result.finish_reason == "stop"
    assert result.usage == {"prompt_tokens": 7, "completion_tokens": 3}
    # The JSON schema is forwarded to Ollama as the structured-output format.
    import json as _json

    sent = _json.loads(route.calls.last.request.content)
    assert sent["format"] == schema
    assert sent["stream"] is False


@respx.mock
def test_generate_forwards_options_and_handles_missing_usage() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "ok"}})
    )
    req = GenerationRequest(
        messages=[ChatMessage(Role.USER, "hi")], model="qwen3:8b", temperature=0.2, max_tokens=64
    )
    result = run(lambda p: p.generate(req))
    assert result.usage == {}  # no token counts in the response
    import json as _json

    sent = _json.loads(route.calls.last.request.content)
    assert sent["options"] == {"temperature": 0.2, "num_predict": 64}


def test_context_manager_does_not_close_injected_client() -> None:
    @respx.mock
    async def _inner() -> None:
        respx.post(f"{BASE}/api/embed").mock(
            return_value=httpx.Response(200, json={"embeddings": [[1.0]]})
        )
        client = httpx.AsyncClient()
        async with OllamaProvider(base_url=BASE, client=client) as provider:
            result = await provider.embed(["x"], "m")
            assert result.dimensions == 1
        assert client.is_closed is False  # injected client is not owned, so not closed
        await client.aclose()

    asyncio.run(_inner())


@respx.mock
def test_stream_yields_ordered_chunks_and_thinking() -> None:
    body = (
        b'{"message":{"thinking":"hmm","content":""}}\n'
        b"\n"  # blank keep-alive line should be skipped
        b'{"message":{"content":"He"}}\n'
        b'{"message":{"content":"llo"},"done":true,"done_reason":"stop"}\n'
    )
    respx.post(f"{BASE}/api/chat").mock(return_value=httpx.Response(200, content=body))

    async def _collect() -> list[tuple[str, str | None, bool]]:
        provider = OllamaProvider(base_url=BASE)
        try:
            return [
                (c.delta, c.thinking, c.done)
                async for c in provider.stream(
                    GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="qwen3:8b")
                )
            ]
        finally:
            await provider.aclose()

    chunks = asyncio.run(_collect())
    assert [c[0] for c in chunks] == ["", "He", "llo"]
    assert chunks[0][1] == "hmm"
    assert chunks[-1][2] is True


@respx.mock
def test_generate_forwards_think_flag_and_captures_thinking() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(
            200, json={"message": {"content": "answer", "thinking": "reasoning"}}
        )
    )
    req = GenerationRequest(
        messages=[ChatMessage(Role.USER, "hi")], model="qwen3.6:35b-a3b", think=False
    )
    result = run(lambda p: p.generate(req))
    assert result.text == "answer"
    assert result.thinking == "reasoning"
    import json as _json

    sent = _json.loads(route.calls.last.request.content)
    assert sent["think"] is False


@respx.mock
def test_embed_returns_vectors_and_dimensions() -> None:
    respx.post(f"{BASE}/api/embed").mock(
        return_value=httpx.Response(
            200, json={"model": "mxbai-embed-large", "embeddings": [[0.1, 0.2, 0.3]]}
        )
    )
    result = run(lambda p: p.embed(["hello"], "mxbai-embed-large"))
    assert result.dimensions == 3
    assert result.vectors == [[0.1, 0.2, 0.3]]


@respx.mock
def test_list_models_combines_tags_and_capabilities() -> None:
    respx.get(f"{BASE}/api/tags").mock(
        return_value=httpx.Response(
            200, json={"models": [{"name": "qwen3:8b"}, {"name": "mxbai-embed-large"}, {}]}
        )
    )
    respx.post(f"{BASE}/api/show").mock(
        side_effect=[
            httpx.Response(200, json={"capabilities": ["completion", "tools"], "model_info": {}}),
            httpx.Response(200, json={"capabilities": ["embedding"], "model_info": {}}),
        ]
    )
    models = run(lambda p: p.list_models())
    assert [m.name for m in models] == [
        "qwen3:8b",
        "mxbai-embed-large",
    ]  # entry without name skipped
    assert models[0].capabilities.tool_calling is True
    assert models[1].capabilities.embeddings is True
    assert models[0].local is True


@respx.mock
def test_list_models_fast_path_uses_only_tags() -> None:
    # capabilities + context_length present in /api/tags -> no /api/show call (none is mocked).
    respx.get(f"{BASE}/api/tags").mock(
        return_value=httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "qwen3:8b",
                        "capabilities": ["completion", "tools", "thinking"],
                        "details": {"context_length": 40960},
                    }
                ]
            },
        )
    )
    models = run(lambda p: p.list_models())
    assert models[0].name == "qwen3:8b"
    assert models[0].local is True
    assert models[0].capabilities.tool_calling is True
    assert models[0].capabilities.max_context_tokens == 40960


@respx.mock
def test_list_models_flags_cloud_and_warns_on_use(caplog: pytest.LogCaptureFixture) -> None:
    respx.get(f"{BASE}/api/tags").mock(
        return_value=httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "qwen3:8b",
                        "capabilities": ["completion"],
                        "details": {"context_length": 40960},
                    },
                    {
                        "name": "kimi-k2.6:cloud",
                        "capabilities": ["completion", "vision"],
                        "details": {"context_length": 256000},
                        "remote_host": "https://ollama.com:443",
                    },
                ]
            },
        )
    )
    respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "hi"}})
    )

    async def _run() -> None:
        provider = OllamaProvider(base_url=BASE)
        try:
            models = await provider.list_models()
            by_name = {m.name: m for m in models}
            assert by_name["qwen3:8b"].local is True
            assert by_name["kimi-k2.6:cloud"].local is False
            with caplog.at_level(logging.WARNING):
                await provider.generate(
                    GenerationRequest(
                        messages=[ChatMessage(Role.USER, "hi")], model="kimi-k2.6:cloud"
                    )
                )
            assert "remote/cloud" in caplog.text
        finally:
            await provider.aclose()

    asyncio.run(_run())


@respx.mock
def test_embed_sends_truncate_flag() -> None:
    route = respx.post(f"{BASE}/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[0.1]]})
    )
    run(lambda p: p.embed(["x"], "m"))
    assert _json.loads(route.calls.last.request.content)["truncate"] is True
    run(lambda p: p.embed(["x"], "m", truncate=False))
    assert _json.loads(route.calls.last.request.content)["truncate"] is False


@respx.mock
def test_http_error_propagates() -> None:
    respx.post(f"{BASE}/api/chat").mock(return_value=httpx.Response(500))
    req = GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="qwen3:8b")
    with pytest.raises(httpx.HTTPStatusError):
        run(lambda p: p.generate(req))
