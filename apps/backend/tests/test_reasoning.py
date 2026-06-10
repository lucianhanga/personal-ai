"""The `reasoning` amount control maps to think + an optional brief hint (no DB needed)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import bootstrap
from personalai_contracts.ports import GenerationChunk, GenerationRequest, Role
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class _Recorder(FakeModelProvider):
    def __init__(self) -> None:
        super().__init__(name="rec")
        self.last: GenerationRequest | None = None

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        self.last = request
        yield GenerationChunk(delta="ok")
        yield GenerationChunk(done=True, finish_reason="stop")


def _send(reasoning: str) -> GenerationRequest:
    rec = _Recorder()
    boot = bootstrap(config=CoreConfig(auth_token=TOKEN, model_provider="rec"))
    boot.registries.model_providers.register("rec", rec, overwrite=True)
    with (
        TestClient(create_app(boot)) as client,
        client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}], "reasoning": reasoning},
        ) as resp,
    ):
        assert resp.status_code == 200
        "".join(resp.iter_text())
    assert rec.last is not None
    return rec.last


def test_reasoning_off_disables_think() -> None:
    assert _send("off").think is False


def test_reasoning_full_enables_think_no_hint() -> None:
    gen = _send("full")
    assert gen.think is True
    assert not any(m.role == Role.SYSTEM and "brief" in m.content.lower() for m in gen.messages)


def test_reasoning_brief_thinks_and_injects_hint() -> None:
    gen = _send("brief")
    assert gen.think is True
    assert any(m.role == Role.SYSTEM and "brief" in m.content.lower() for m in gen.messages)


def _send_grounding(*, enabled: bool) -> GenerationRequest:
    rec = _Recorder()
    boot = bootstrap(
        config=CoreConfig(auth_token=TOKEN, model_provider="rec", grounding_enabled=enabled)
    )
    boot.registries.model_providers.register("rec", rec, overwrite=True)
    with (
        TestClient(create_app(boot)) as client,
        client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}]},
        ) as resp,
    ):
        assert resp.status_code == 200
        "".join(resp.iter_text())
    assert rec.last is not None
    return rec.last


def test_grounding_prompt_injected_by_default() -> None:
    gen = _send_grounding(enabled=True)
    assert any(m.role == Role.SYSTEM and "fabricate" in m.content.lower() for m in gen.messages)


def test_grounding_prompt_absent_when_disabled() -> None:
    gen = _send_grounding(enabled=False)
    assert not any(m.role == Role.SYSTEM and "fabricate" in m.content.lower() for m in gen.messages)
