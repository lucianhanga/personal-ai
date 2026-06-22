"""Tool-equipped frontier adapter: function-calling loop over mocked model + tools (#328)."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from personalai_benchmarks import frontier_tools


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


_TOOLS = {
    "data": {
        "tools": [
            {
                "name": "calculator",
                "version": "1.0.0",
                "permissions": [],
                "inputs": {"type": "object", "properties": {"expression": {"type": "string"}}},
            }
        ]
    }
}


def _calc_then_answer() -> Callable[[httpx.Request], httpx.Response]:
    """Backend serves the tool list + invoke; the model asks for the calculator, then answers."""
    state = {"chat": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/api/v1/tools"):
            return httpx.Response(200, json=_TOOLS)
        if url.endswith("/api/v1/tools/invoke"):
            assert json.loads(request.content)["tool"] == "calculator"
            return httpx.Response(200, json={"ok": True, "data": {"result": 7006652}})
        if url.endswith("/chat/completions"):
            state["chat"] += 1
            if state["chat"] == 1:
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [
                                        {
                                            "id": "c1",
                                            "type": "function",
                                            "function": {
                                                "name": "calculator",
                                                "arguments": json.dumps(
                                                    {"expression": "1234*5678"}
                                                ),
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "The answer is 7006652."}}]},
            )
        return httpx.Response(404, text=f"unexpected {url}")

    return handler


def test_runs_the_tool_loop_and_returns_the_final_answer() -> None:
    adapter = frontier_tools.build(
        "openai", api_key="sk", backend_url="http://bk", client=_client(_calc_then_answer())
    )
    assert adapter is not None and adapter.name == "openai+tools:gpt-5.4-mini"
    result = adapter.run([{"role": "user", "content": "what is 1234*5678?"}], {})
    assert result.error is None
    assert "7006652" in result.answer
    assert result.tool_calls == [{"tool": "calculator", "args": {"expression": "1234*5678"}}]
    assert result.config_used["tier"] == "frontier_tools"


def test_build_skips_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert frontier_tools.build("xai", backend_url="http://bk") is None


def test_tool_error_is_fed_back_not_fatal() -> None:
    state = {"chat": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/api/v1/tools"):
            return httpx.Response(200, json=_TOOLS)
        if url.endswith("/api/v1/tools/invoke"):
            return httpx.Response(200, json={"ok": False, "error": {"message": "bad expression"}})
        state["chat"] += 1
        if state["chat"] == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "id": "c1",
                                        "type": "function",
                                        "function": {"name": "calculator", "arguments": "{}"},
                                    }
                                ]
                            }
                        }
                    ]
                },
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "I could not compute that."}}]}
        )

    adapter = frontier_tools.build(
        "openai", api_key="sk", backend_url="http://bk", client=_client(handler)
    )
    assert adapter is not None
    result = adapter.run([{"role": "user", "content": "compute"}], {})
    assert result.error is None and "could not" in result.answer  # tool failure -> model recovers


def test_http_error_is_captured() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/api/v1/tools"):
            return httpx.Response(500, text="backend down")
        return httpx.Response(404)

    adapter = frontier_tools.build(
        "openai", api_key="sk", backend_url="http://bk", client=_client(handler)
    )
    assert adapter is not None
    assert adapter.run([{"role": "user", "content": "hi"}], {}).error is not None
