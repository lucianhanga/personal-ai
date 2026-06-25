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
