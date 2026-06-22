"""POST /api/v1/assistant/execute: one-shot run, per-run overrides, no settings mutation (#313)."""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from starlette.applications import Starlette

from personalai_backend import create_app
from personalai_backend.composition import bootstrap
from personalai_contracts.ports import (
    GenerationRequest,
    GenerationResult,
    ModelProvider,
    ToolCallRequest,
)
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
# Unreachable DB -> the app degrades to storage-less mode, so the turn runs purely from config and
# never picks up per-tenant settings that would change the path.
DB = "postgresql://personalai@127.0.0.1:1/personalai"


def _client(provider_name: str = "plain", provider: ModelProvider | None = None) -> TestClient:
    config = CoreConfig(auth_token=TOKEN, model_provider=provider_name, database_url=DB)
    boot = bootstrap(config=config)
    boot.registries.model_providers.register(
        provider_name, provider or FakeModelProvider(name=provider_name)
    )
    return TestClient(create_app(boot))


def _execute(client: TestClient, **body: object) -> dict[str, Any]:
    body.setdefault("messages", [{"role": "user", "content": "hi"}])
    resp = client.post("/api/v1/assistant/execute", headers=AUTH, json=body)
    assert resp.status_code == 200, resp.text
    return cast(dict[str, Any], resp.json())


def test_execute_returns_answer_and_config_used() -> None:
    with _client() as client:
        body = _execute(client)
    assert body["ok"] is True
    data = body["data"]
    assert "echo:" in data["answer"]  # the plain fake echoes
    cu = data["config_used"]
    assert cu["agent_mode"] == "single"
    assert cu["use_tools"] is False and cu["use_mcp"] is True
    assert isinstance(data["latency_ms"], int | float)
    assert isinstance(data["trace"], list) and isinstance(data["tool_calls"], list)


class _Scripted(FakeModelProvider):
    """Asks for the calculator once, then answers."""

    def __init__(self) -> None:
        super().__init__(name="scripted")
        self._n = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self._n += 1
        if self._n == 1:
            return GenerationResult(
                text="",
                model=request.model,
                tool_calls=[ToolCallRequest(name="calculator", arguments={"expression": "23*19"})],
            )
        return GenerationResult(text="It is 437.", model=request.model)


def test_execute_with_tools_records_tool_calls_and_trace() -> None:
    with _client("scripted", _Scripted()) as client:
        data = _execute(
            client,
            messages=[{"role": "user", "content": "what is 23*19?"}],
            use_tools=True,
        )["data"]
    assert "437" in data["answer"]  # real calculator ran (23*19)
    assert any(tc["tool"] == "calculator" for tc in data["tool_calls"])
    assert any(t.get("tool") == "calculator" for t in data["trace"])
    assert data["config_used"]["use_tools"] is True


def test_use_mcp_false_limits_tools_to_builtins() -> None:
    with _client() as client:
        cu = _execute(client, use_mcp=False)["data"]["config_used"]
    assert set(cu["tools_available"]) <= {"calculator", "web_search", "http_fetch", "remember"}
    assert cu["use_mcp"] is False


def test_execute_reflects_overrides_without_mutating_boot_config() -> None:
    with _client() as client:
        state = cast(Starlette, client.app).state
        before_mode = state.config.agent_mode
        before_grounding = state.config.grounding_enabled
        cu = _execute(client, grounding=True, max_iterations=3, temperature=0.2)["data"][
            "config_used"
        ]
        assert cu["grounding"] is True
        assert cu["max_iterations"] == 3
        assert cu["temperature"] == 0.2
        # The overrides applied only to a per-request copy — the boot config is untouched.
        assert state.config.agent_mode == before_mode
        assert state.config.grounding_enabled == before_grounding


def test_execute_requires_auth() -> None:
    with _client() as client:
        resp = client.post(
            "/api/v1/assistant/execute",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
    assert resp.status_code == 401
