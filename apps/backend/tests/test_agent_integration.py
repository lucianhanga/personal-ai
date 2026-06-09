"""Opt-in agent integration test against a live Ollama (skipped in CI).

Run with:  PERSONALAI_OLLAMA_IT=1 uv run pytest apps/backend/tests/test_agent_integration.py -q
Needs a local Ollama serving a tools-capable model (override with PERSONALAI_IT_MODEL).
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import bootstrap
from personalai_core import CoreConfig

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
IT = os.environ.get("PERSONALAI_OLLAMA_IT") == "1"
MODEL = os.environ.get("PERSONALAI_IT_MODEL", "qwen3:8b")


@pytest.mark.skipif(not IT, reason="set PERSONALAI_OLLAMA_IT=1 to run against a live Ollama")
def test_agent_calls_calculator_against_real_model() -> None:
    boot = bootstrap(config=CoreConfig(auth_token=TOKEN, default_model=MODEL))
    with (
        TestClient(create_app(boot)) as client,
        client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={
                "model": MODEL,
                "use_tools": True,
                "messages": [{"role": "user", "content": "What is 23 * 19? Use the calculator."}],
            },
        ) as resp,
    ):
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    assert "event: tool" in body  # the model actually called a tool
    assert "calculator" in body
    assert "437" in body  # correct result, streamed back in the answer
