"""Per-conversation tagging + filtering of the tool log and app logs."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import bootstrap
from personalai_backend.logbuffer import RingBufferHandler
from personalai_contracts.ports import GenerationRequest, GenerationResult, Role, ToolCallRequest
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig
from personalai_core.security import current_conversation

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class _ToolThenAnswer(FakeModelProvider):
    """Request-stateless: calls the calculator until a tool result is in the conversation."""

    def __init__(self) -> None:
        super().__init__(name="ollama")

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        if not any(m.role == Role.TOOL for m in request.messages):
            return GenerationResult(
                text="",
                model=request.model,
                tool_calls=[ToolCallRequest(name="calculator", arguments={"expression": "2+2"})],
            )
        return GenerationResult(text="4.", model=request.model)


def _client() -> TestClient:
    boot = bootstrap(config=CoreConfig(auth_token=TOKEN, model_provider="ollama"))
    boot.registries.model_providers.register("ollama", _ToolThenAnswer(), overwrite=True)
    return TestClient(create_app(boot))


def _run_tool_chat(client: TestClient, conversation_id: str) -> None:
    with client.stream(
        "POST",
        "/api/chat",
        headers=AUTH,
        json={
            "messages": [{"role": "user", "content": "2+2?"}],
            "use_tools": True,
            "conversation_id": conversation_id,
        },
    ) as resp:
        assert resp.status_code == 200
        "".join(resp.iter_text())  # drain the stream so the agent + audit run


def test_tool_log_is_tagged_and_filtered_by_conversation() -> None:
    client = _client()
    _run_tool_chat(client, "conv-A")
    _run_tool_chat(client, "conv-B")

    a = client.get("/api/tools/log", params={"conversation_id": "conv-A"}, headers=AUTH)
    entries = a.json()["data"]["entries"]
    assert entries and all(e["conversation"] == "conv-A" for e in entries)
    assert any(e["tool"] == "calculator" for e in entries)

    none = client.get("/api/tools/log", params={"conversation_id": "zzz"}, headers=AUTH)
    assert none.json()["data"]["entries"] == []

    # Unfiltered still returns calls from both conversations.
    everything = client.get("/api/tools/log", headers=AUTH).json()["data"]["entries"]
    convs = {e["conversation"] for e in everything}
    assert {"conv-A", "conv-B"} <= convs


def test_log_record_tagged_with_conversation() -> None:
    handler = RingBufferHandler()
    token = current_conversation.set("conv-X")
    try:
        handler.emit(
            logging.LogRecord("personalai.x", logging.WARNING, __file__, 0, "scoped", None, None)
        )
    finally:
        current_conversation.reset(token)
    assert handler.records[-1]["conversation"] == "conv-X"


def test_logs_endpoint_filters_by_conversation() -> None:
    client = _client()
    token = current_conversation.set("conv-Y")
    try:
        logging.getLogger("personalai_backend.demo").warning("chat-scoped-log")
    finally:
        current_conversation.reset(token)
    logging.getLogger("personalai_backend.demo").warning("global-log")

    y = client.get("/api/logs", params={"conversation_id": "conv-Y"}, headers=AUTH)
    logs = y.json()["data"]["logs"]
    assert any(r["message"] == "chat-scoped-log" for r in logs)
    assert all(r["conversation"] == "conv-Y" for r in logs)
    assert not any(r["message"] == "global-log" for r in logs)
