"""OpenAICompatProvider against a mocked OpenAI-compatible API (respx)."""

from __future__ import annotations

import asyncio
import json as _json
from collections.abc import Awaitable, Callable

import httpx
import pytest
import respx

from personalai_contracts.ports import (
    ChatMessage,
    GenerationChunk,
    GenerationRequest,
    ModelProvider,
    Role,
    ToolSpec,
)
from personalai_provider_openai import OpenAICompatProvider

BASE = "https://api.example.test/v1"


def run[R](call: Callable[[OpenAICompatProvider], Awaitable[R]]) -> R:
    async def _inner() -> R:
        provider = OpenAICompatProvider(api_key="sk-test", base_url=BASE)
        try:
            return await call(provider)
        finally:
            await provider.aclose()

    return asyncio.run(_inner())


def test_is_a_model_provider() -> None:
    assert isinstance(OpenAICompatProvider(api_key="k", base_url=BASE), ModelProvider)


@respx.mock
def test_generate_passes_tools_and_parses_tool_calls() -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "calculator",
                                        "arguments": '{"expression": "2+2"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            },
        )
    )
    tools = [ToolSpec(name="calculator", description="math", parameters={"type": "object"})]
    req = GenerationRequest(
        messages=[ChatMessage(Role.USER, "2+2?")], model="gpt-4o-mini", tools=tools
    )
    result = run(lambda p: p.generate(req))
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "calculator"
    assert result.tool_calls[0].arguments == {"expression": "2+2"}  # JSON string parsed
    assert result.tool_calls[0].id == "call_1"

    import json as _json

    sent = _json.loads(route.calls.last.request.content)
    assert sent["tools"][0]["function"]["name"] == "calculator"


@respx.mock
def test_generate_maps_response_sends_key_and_schema() -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "gpt-x",
                "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )
    )
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    req = GenerationRequest(
        messages=[ChatMessage(Role.USER, "hi")], model="gpt-x", json_schema=schema
    )
    result = run(lambda p: p.generate(req))
    assert result.text == "hello"
    assert result.finish_reason == "stop"
    assert result.usage == {"prompt_tokens": 5, "completion_tokens": 2}

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer sk-test"
    body = _json.loads(request.content)
    assert body["response_format"]["json_schema"]["schema"] == schema


@respx.mock
def test_stream_parses_sse_until_done() -> None:
    body = (
        b'data: {"choices":[{"delta":{"content":"He"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(200, content=body))

    async def _collect() -> list[tuple[str, bool]]:
        provider = OpenAICompatProvider(api_key="k", base_url=BASE)
        try:
            return [
                (c.delta, c.done)
                async for c in provider.stream(
                    GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="gpt-x")
                )
            ]
        finally:
            await provider.aclose()

    chunks = asyncio.run(_collect())
    assert [c[0] for c in chunks] == ["He", "llo", ""]
    assert chunks[-1][1] is True


@respx.mock
def test_stream_reassembles_tool_calls() -> None:
    # OpenAI streams tool-call name + argument fragments across chunks; we reassemble them.
    body = (
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
        b'"function":{"name":"calculator","arguments":"{\\"expr"}}]}}]}\n\n'
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        b'"function":{"arguments":"ession\\": \\"2+2\\"}"}}]}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(200, content=body))

    async def _collect() -> list[GenerationChunk]:
        provider = OpenAICompatProvider(api_key="k", base_url=BASE)
        try:
            return [
                c
                async for c in provider.stream(
                    GenerationRequest(messages=[ChatMessage(Role.USER, "2+2?")], model="gpt-x")
                )
            ]
        finally:
            await provider.aclose()

    chunks = asyncio.run(_collect())
    done = chunks[-1]
    assert done.done is True
    assert len(done.tool_calls) == 1
    assert done.tool_calls[0].name == "calculator"
    assert done.tool_calls[0].arguments == {"expression": "2+2"}
    assert done.tool_calls[0].id == "c1"


@respx.mock
def test_list_models_marks_remote() -> None:
    respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "gpt-x"}, {"id": "gpt-y"}, {}]})
    )
    models = run(lambda p: p.list_models())
    assert [m.name for m in models] == ["gpt-x", "gpt-y"]
    assert all(m.local is False for m in models)


@respx.mock
def test_embed_returns_vectors() -> None:
    respx.post(f"{BASE}/embeddings").mock(
        return_value=httpx.Response(200, json={"model": "emb", "data": [{"embedding": [0.1, 0.2]}]})
    )
    result = run(lambda p: p.embed(["hi"], "emb"))
    assert result.dimensions == 2
    assert result.vectors == [[0.1, 0.2]]


def test_egress_guard_blocks_before_any_request() -> None:
    class Blocked(Exception):
        pass

    def deny(host: str) -> None:
        raise Blocked(host)

    async def _run() -> None:
        provider = OpenAICompatProvider(api_key="k", base_url=BASE, egress_guard=deny)
        try:
            with pytest.raises(Blocked, match="api.example.test"):
                await provider.generate(
                    GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="gpt-x")
                )
        finally:
            await provider.aclose()

    asyncio.run(_run())


@respx.mock
def test_generate_forwards_options_and_capabilities() -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    )
    req = GenerationRequest(
        messages=[ChatMessage(Role.USER, "hi")], model="gpt-x", temperature=0.3, max_tokens=32
    )
    run(lambda p: p.generate(req))
    body = _json.loads(route.calls.last.request.content)
    assert body["temperature"] == 0.3
    assert body["max_tokens"] == 32

    caps = run(lambda p: p.capabilities("gpt-x"))
    assert caps.text is True
    assert caps.tool_calling is True


@respx.mock
def test_stream_without_done_terminator() -> None:
    body = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(200, content=body))

    async def _collect() -> list[str]:
        provider = OpenAICompatProvider(api_key="k", base_url=BASE)
        try:
            return [
                c.delta
                async for c in provider.stream(
                    GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="gpt-x")
                )
            ]
        finally:
            await provider.aclose()

    assert asyncio.run(_collect()) == ["hi"]


def test_context_manager_does_not_close_injected_client() -> None:
    @respx.mock
    async def _inner() -> None:
        respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json={"data": []}))
        client = httpx.AsyncClient()
        async with OpenAICompatProvider(api_key="k", base_url=BASE, client=client) as provider:
            await provider.list_models()
        assert client.is_closed is False
        await client.aclose()

    asyncio.run(_inner())


@respx.mock
def test_http_error_propagates() -> None:
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(401))
    req = GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="gpt-x")
    with pytest.raises(httpx.HTTPStatusError):
        run(lambda p: p.generate(req))
