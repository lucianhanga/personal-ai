"""generate_structured: bounded, fail-closed structured-output generation (M8.2, #261)."""

from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import BaseModel

from personalai_contracts.ports import ChatMessage, GenerationRequest, GenerationResult, Role
from personalai_contracts.testing import FakeModelProvider
from personalai_core import generate_structured


class _Verdict(BaseModel):
    verdict: Literal["pass", "fail"]
    reason: str


def _run(provider: FakeModelProvider) -> _Verdict | None:
    async def go() -> _Verdict | None:
        return await generate_structured(
            provider=provider,
            model="m",
            messages=[ChatMessage(Role.USER, "judge this")],
            schema=_Verdict,
        )

    return asyncio.run(go())


class _ValidJson(FakeModelProvider):
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            text='Here is my verdict: {"verdict": "pass", "reason": "looks good"}',
            model=request.model,
        )


def test_parses_and_validates_structured_output() -> None:
    result = _run(_ValidJson())
    assert result is not None
    assert result.verdict == "pass" and result.reason == "looks good"


class _RepairThenValid(FakeModelProvider):
    """First reply is invalid (bad enum); the repair attempt returns valid JSON."""

    def __init__(self) -> None:
        super().__init__(name="repair")
        self._n = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self._n += 1
        if self._n == 1:
            return GenerationResult(text='{"verdict": "maybe", "reason": "x"}', model=request.model)
        # The second call should have received a repair message asking for valid JSON.
        assert any("invalid" in m.content.lower() for m in request.messages)
        return GenerationResult(text='{"verdict": "fail", "reason": "wrong"}', model=request.model)


def test_repairs_an_invalid_payload_within_the_budget() -> None:
    result = _run(_RepairThenValid())
    assert result is not None and result.verdict == "fail"


class _ListThenValid(FakeModelProvider):
    """First reply is a JSON list (wrong shape, not an object) — e.g. a vision planner returning
    `[]`; the repair attempt returns valid JSON. Regression for the RepairRequest validation crash:
    invalid_payload must accept a non-dict so the repair loop feeds the bad output back."""

    def __init__(self) -> None:
        super().__init__(name="list")
        self._n = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self._n += 1
        if self._n == 1:
            return GenerationResult(text="[]", model=request.model)
        return GenerationResult(text='{"verdict": "fail", "reason": "wrong"}', model=request.model)


def test_repairs_when_model_returns_a_json_list_not_an_object() -> None:
    # A model returning a JSON list instead of an object must not crash the repair loop building a
    # RepairRequest (invalid_payload accepts any JSON, not only a Mapping).
    result = _run(_ListThenValid())
    assert result is not None and result.verdict == "fail"


class _AlwaysInvalid(FakeModelProvider):
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(text="not json at all", model=request.model)


def test_fails_closed_when_repair_is_exhausted() -> None:
    # Every attempt is unparseable -> None (the caller must not act on an unvalidated payload).
    assert _run(_AlwaysInvalid()) is None


class _Recorder(FakeModelProvider):
    """Records each GenerationRequest so the MoE structured-output workaround can be asserted."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        return GenerationResult(text='{"verdict": "pass", "reason": "ok"}', model=request.model)


def _structured_for(model: str) -> _Recorder:
    rec = _Recorder()

    async def go() -> None:
        await generate_structured(
            provider=rec, model=model, messages=[ChatMessage(Role.USER, "x")], schema=_Verdict
        )

    asyncio.run(go())
    return rec


def test_moe_omits_think_and_prepends_no_think(model: str = "qwen3.6:35b-a3b") -> None:
    # #461: on the MoE arch, `think=False`+`format` is silently ignored (prose). The fix omits
    # `think` (so `format` is honored) and prepends "/no_think" (so no reasoning trace leaks).
    req = _structured_for(model).requests[0]
    assert req.think is None
    assert req.messages[0].role == Role.SYSTEM and req.messages[0].content == "/no_think"


def test_dense_model_keeps_think_false_and_no_prefix() -> None:
    req = _structured_for("qwen3:14b").requests[0]
    assert req.think is False
    assert not (req.messages[0].role == Role.SYSTEM and req.messages[0].content == "/no_think")
