"""Context-usage SSE event from /api/chat (no DB needed)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import bootstrap
from personalai_contracts.ports import (
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    ToolCallRequest,
)
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class _UsageProvider(FakeModelProvider):
    """Streams a couple of tokens then a done chunk carrying token usage."""

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        yield GenerationChunk(delta="hi ")
        yield GenerationChunk(
            done=True,
            finish_reason="stop",
            usage={"prompt_tokens": 100, "completion_tokens": 20},
        )


def _client(provider_name: str) -> TestClient:
    boot = bootstrap(config=CoreConfig(auth_token=TOKEN, model_provider=provider_name))
    boot.registries.model_providers.register(
        provider_name, _UsageProvider(name=provider_name), overwrite=True
    )
    return TestClient(create_app(boot))


def _body(client: TestClient, payload: dict[str, object]) -> str:
    with client.stream("POST", "/api/chat", headers=AUTH, json=payload) as resp:
        assert resp.status_code == 200
        return "".join(resp.iter_text())


def test_usage_event_for_ollama_includes_context_limit() -> None:
    body = _body(_client("ollama"), {"messages": [{"role": "user", "content": "hi"}]})
    assert "event: usage" in body
    assert '"prompt_tokens": 100' in body
    assert '"total_tokens": 120' in body
    assert '"context_limit": 32768' in body  # the bound Ollama window


def test_usage_event_for_remote_has_no_context_limit() -> None:
    body = _body(_client("openai"), {"messages": [{"role": "user", "content": "hi"}]})
    assert "event: usage" in body
    assert '"context_limit": null' in body


def test_usage_event_in_tools_path() -> None:
    class _ScriptedUsage(FakeModelProvider):
        def __init__(self) -> None:
            super().__init__(name="ollama")
            self._n = 0

        async def generate(self, request: GenerationRequest) -> GenerationResult:
            self._n += 1
            if self._n == 1:
                return GenerationResult(
                    text="",
                    model=request.model,
                    tool_calls=[
                        ToolCallRequest(name="calculator", arguments={"expression": "1+1"})
                    ],
                )
            return GenerationResult(
                text="2.", model=request.model, usage={"prompt_tokens": 50, "completion_tokens": 5}
            )

    boot = bootstrap(config=CoreConfig(auth_token=TOKEN, model_provider="ollama"))
    boot.registries.model_providers.register("ollama", _ScriptedUsage(), overwrite=True)
    client = TestClient(create_app(boot))
    body = _body(client, {"messages": [{"role": "user", "content": "1+1?"}], "use_tools": True})
    assert "event: usage" in body
    assert '"total_tokens": 55' in body
