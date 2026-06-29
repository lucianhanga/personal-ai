"""The `reasoning` amount control maps to think + a graded reasoning-budget nudge (no DB needed)."""

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


def test_reasoning_off_disables_think_no_nudge() -> None:
    gen = _send("off")
    assert gen.think is False
    assert not any(m.role == Role.SYSTEM and "/think" in m.content for m in gen.messages)


def test_reasoning_low_thinks_with_brief_nudge() -> None:
    gen = _send("low")
    assert gen.think is True
    assert any(m.role == Role.SYSTEM and "briefly" in m.content.lower() for m in gen.messages)


def test_reasoning_medium_thinks_with_nudge() -> None:
    gen = _send("medium")
    assert gen.think is True
    assert any(m.role == Role.SYSTEM and "/think" in m.content for m in gen.messages)


def test_reasoning_high_thinks_with_thorough_nudge() -> None:
    gen = _send("high")
    assert gen.think is True
    assert any(m.role == Role.SYSTEM and "thoroughly" in m.content.lower() for m in gen.messages)


def test_resolve_reasoning_maps_levels_to_distinct_nudges() -> None:
    from personalai_backend.app import _resolve_reasoning

    assert _resolve_reasoning(None, True) == (True, [])  # None -> raw think flag
    think_off, msgs_off = _resolve_reasoning("off", True)
    assert think_off is False and msgs_off == []  # off overrides think, no nudge
    nudges = set()
    for lvl in ("low", "medium", "high"):
        think, msgs = _resolve_reasoning(lvl, False)
        assert think is True and len(msgs) == 1 and "/think" in msgs[0].content
        nudges.add(msgs[0].content)
    assert len(nudges) == 3  # a real gradient: the three nudges are distinct


def test_current_datetime_injected_as_authoritative_ground_truth() -> None:
    from datetime import datetime

    gen = _send("high")
    today = datetime.now().astimezone().date().isoformat()
    msg = next(
        (
            m.content
            for m in gen.messages
            if m.role == Role.SYSTEM and "current date and time" in m.content.lower()
        ),
        None,
    )
    assert msg is not None  # every turn injects the authoritative 'now'
    assert today in msg  # the actual current date, not a placeholder
    assert "ground truth" in msg.lower()
    assert "training-data cutoff" in msg.lower()  # overrides the model's cutoff prior


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
