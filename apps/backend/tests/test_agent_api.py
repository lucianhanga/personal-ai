"""Agent loop via /api/chat use_tools (no DB needed; gateway runs the real calculator)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import bootstrap
from personalai_contracts.ports import GenerationRequest, GenerationResult, ToolCallRequest
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


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


def _client() -> TestClient:
    config = CoreConfig(auth_token=TOKEN, model_provider="scripted")
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("scripted", _Scripted())
    return TestClient(create_app(boot))


def test_use_tools_runs_agent_and_emits_tool_events() -> None:
    with (
        _client() as client,
        client.stream(
            "POST",
            "/api/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "what is 23*19?"}], "use_tools": True},
        ) as resp,
    ):
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    assert "event: tool" in body  # tool steps streamed
    assert "calculator" in body
    assert "437" in body  # real calculator result (23*19) + the final answer


def test_chat_without_tools_still_streams() -> None:
    # A plain echo provider (no scripted tool calls) on the non-tools path.
    config = CoreConfig(auth_token=TOKEN, model_provider="plain")
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("plain", FakeModelProvider(name="plain"))
    with (
        TestClient(create_app(boot)) as client,
        client.stream(
            "POST",
            "/api/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}]},
        ) as resp,
    ):
        body = "".join(resp.iter_text())
    assert "event: tool" not in body
    assert "echo:" in body  # streamed answer (no tool steps)
