"""OllamaProvider against a mocked Ollama REST API (respx) — no live server needed."""

from __future__ import annotations

import asyncio
import json as _json
import logging
from collections.abc import Awaitable, Callable

import httpx
import pytest
import respx

from personalai_contracts.ports import (
    ChatMessage,
    GenerationRequest,
    ModelProvider,
    Role,
    ToolSpec,
)
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
    caps = run(lambda p: p.capabilities("qwen3-embedding:0.6b"))
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
def test_generate_passes_tools_and_parses_tool_calls() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "qwen3:8b",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "calculator", "arguments": {"expression": "2+2"}}}
                    ],
                },
                "done_reason": "stop",
            },
        )
    )
    tools = [ToolSpec(name="calculator", description="math", parameters={"type": "object"})]
    req = GenerationRequest(
        messages=[ChatMessage(Role.USER, "2+2?")], model="qwen3:8b", tools=tools
    )
    result = run(lambda p: p.generate(req))
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "calculator"
    assert result.tool_calls[0].arguments == {"expression": "2+2"}

    import json as _json

    sent = _json.loads(route.calls.last.request.content)
    assert sent["tools"][0]["function"]["name"] == "calculator"


@respx.mock
def test_generate_sets_num_ctx_when_configured() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "ok"}})
    )

    async def _run() -> None:
        provider = OllamaProvider(base_url=BASE, num_ctx=32768)
        try:
            await provider.generate(
                GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="qwen3:8b")
            )
        finally:
            await provider.aclose()

    asyncio.run(_run())
    sent = _json.loads(route.calls.last.request.content)
    assert sent["options"]["num_ctx"] == 32768


@respx.mock
def test_configured_sampling_defaults_are_sent_and_temperature_can_be_overridden() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "ok"}})
    )

    async def _run(req: GenerationRequest) -> None:
        provider = OllamaProvider(base_url=BASE, temperature=0.7, top_p=0.8, top_k=20)
        try:
            await provider.generate(req)
        finally:
            await provider.aclose()

    # No per-request temperature -> the configured defaults are applied (grounded sampling).
    asyncio.run(_run(GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="qwen3:8b")))
    opts = _json.loads(route.calls.last.request.content)["options"]
    assert opts["temperature"] == 0.7 and opts["top_p"] == 0.8 and opts["top_k"] == 20

    # An explicit request temperature wins over the default; top_p/top_k still applied.
    asyncio.run(
        _run(
            GenerationRequest(
                messages=[ChatMessage(Role.USER, "hi")], model="qwen3:8b", temperature=0.1
            )
        )
    )
    opts = _json.loads(route.calls.last.request.content)["options"]
    assert opts["temperature"] == 0.1 and opts["top_p"] == 0.8 and opts["top_k"] == 20


@respx.mock
def test_configured_repeat_penalties_are_sent() -> None:
    # Runaway guard Layer 1 (#414): repeat_penalty / repeat_last_n from config land in options.
    route = respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "ok"}})
    )

    async def _run() -> None:
        provider = OllamaProvider(base_url=BASE, repeat_penalty=1.1, repeat_last_n=64)
        try:
            await provider.generate(
                GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="qwen3:8b")
            )
        finally:
            await provider.aclose()

    asyncio.run(_run())
    opts = _json.loads(route.calls.last.request.content)["options"]
    assert opts["repeat_penalty"] == 1.1 and opts["repeat_last_n"] == 64


@respx.mock
def test_max_output_tokens_ceiling_applies_only_when_no_explicit_max_tokens() -> None:
    # Runaway guard Layer 2 (#414): the configured ceiling becomes num_predict on an unbounded turn,
    # but an explicit (smaller) per-request max_tokens still wins.
    route = respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "ok"}})
    )

    async def _run(req: GenerationRequest) -> None:
        provider = OllamaProvider(base_url=BASE, max_output_tokens=4096)
        try:
            await provider.generate(req)
        finally:
            await provider.aclose()

    # No explicit max_tokens (the agent-turn case) -> the ceiling is applied as num_predict.
    asyncio.run(_run(GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="qwen3:8b")))
    opts = _json.loads(route.calls.last.request.content)["options"]
    assert opts["num_predict"] == 4096

    # An explicit smaller max_tokens wins over the ceiling.
    asyncio.run(
        _run(
            GenerationRequest(
                messages=[ChatMessage(Role.USER, "hi")], model="qwen3:8b", max_tokens=128
            )
        )
    )
    opts = _json.loads(route.calls.last.request.content)["options"]
    assert opts["num_predict"] == 128


@respx.mock
def test_length_done_reason_propagates_as_finish_reason() -> None:
    # Runaway guard Layer 2 (#414): a length-capped finish must surface, not be swallowed, so the UI
    # can frame the answer as truncated.
    body = b'{"message":{"content":"partial"},"done":true,"done_reason":"length"}\n'
    respx.post(f"{BASE}/api/chat").mock(return_value=httpx.Response(200, content=body))

    async def _collect() -> list[str | None]:
        provider = OllamaProvider(base_url=BASE)
        try:
            return [
                c.finish_reason
                async for c in provider.stream(
                    GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="qwen3:8b")
                )
            ]
        finally:
            await provider.aclose()

    assert "length" in asyncio.run(_collect())

    # The non-streaming path surfaces it too.
    respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(
            200, json={"message": {"content": "partial"}, "done_reason": "length"}
        )
    )
    result = run(
        lambda p: p.generate(
            GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="qwen3:8b")
        )
    )
    assert result.finish_reason == "length"


@respx.mock
def test_generate_sets_keep_alive_when_configured() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "ok"}})
    )

    async def _run() -> None:
        provider = OllamaProvider(base_url=BASE, keep_alive="30m")
        try:
            await provider.generate(
                GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="qwen3:8b")
            )
        finally:
            await provider.aclose()

    asyncio.run(_run())
    sent = _json.loads(route.calls.last.request.content)
    assert sent["keep_alive"] == "30m"  # keeps the model warm between turns


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
            200, json={"model": "qwen3-embedding:0.6b", "embeddings": [[0.1, 0.2, 0.3]]}
        )
    )
    result = run(lambda p: p.embed(["hello"], "qwen3-embedding:0.6b"))
    assert result.dimensions == 3
    assert result.vectors == [[0.1, 0.2, 0.3]]


@respx.mock
def test_list_models_combines_tags_and_capabilities() -> None:
    respx.get(f"{BASE}/api/tags").mock(
        return_value=httpx.Response(
            200, json={"models": [{"name": "qwen3:8b"}, {"name": "qwen3-embedding:0.6b"}, {}]}
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
        "qwen3-embedding:0.6b",
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


def test_egress_guard_blocks_remote_host() -> None:
    seen: list[str] = []

    def guard(host: str) -> None:
        seen.append(host)
        if host != "127.0.0.1":
            raise RuntimeError(f"egress blocked: {host}")

    remote = OllamaProvider(base_url="http://remote.example:11434", egress_guard=guard)
    with pytest.raises(RuntimeError, match="egress blocked"):
        asyncio.run(remote.list_models())  # _get -> _check_egress -> guard raises
    assert seen == ["remote.example"]


def test_egress_guard_allows_loopback() -> None:
    seen: list[str] = []
    local = OllamaProvider(base_url="http://127.0.0.1:11434", egress_guard=seen.append)
    local._check_egress()  # loopback host passes the guard without raising
    assert seen == ["127.0.0.1"]


def test_chat_payload_includes_images_as_raw_base64() -> None:
    # M9.1: a vision turn carries data-URL images; Ollama wants raw base64 (prefix stripped).
    from personalai_provider_ollama.provider import _chat_payload

    req = GenerationRequest(
        messages=[
            ChatMessage(Role.USER, "what is this?", images=("data:image/png;base64,AAAABBBB",))
        ],
        model="gemma3:27b",
    )
    payload = _chat_payload(req, stream=False)
    msg = payload["messages"][0]
    assert msg["content"] == "what is this?"
    assert msg["images"] == ["AAAABBBB"]  # data-URL prefix stripped


def test_chat_payload_omits_images_for_text_turn() -> None:
    from personalai_provider_ollama.provider import _chat_payload

    req = GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="qwen3:8b")
    assert "images" not in _chat_payload(req, stream=False)["messages"][0]
