"""consolidate_fact: ADD new, NOOP dups, UPDATE/supersede contradictions, fail closed (#310)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence

from personalai_contracts.ports import (
    EmbeddingResult,
    GenerationRequest,
    GenerationResult,
    MemoryKind,
    MemoryStore,
)
from personalai_contracts.testing import FakeModelProvider, InMemoryMemoryStore
from personalai_core import ConsolidationOutcome, consolidate_fact


class _Provider(FakeModelProvider):
    """embed() = one-hot per unique text (so identical text matches itself); generate() = a fixed
    judge decision (or invalid JSON to exercise the fail-closed path)."""

    def __init__(self, decision: str | None, dim: int = 16) -> None:
        super().__init__(name="judge")
        self._decision = decision
        self._dim = dim
        self._idx: dict[str, int] = {}

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(text=self._decision or "not json", model=request.model)

    async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
        out: list[list[float]] = []
        for t in texts:
            self._idx.setdefault(t, len(self._idx))
            vec = [0.0] * self._dim
            vec[self._idx[t]] = 1.0
            out.append(vec)
        return EmbeddingResult(vectors=out, model=model, dimensions=self._dim)


def _consolidate(store: MemoryStore, provider: _Provider, text: str) -> ConsolidationOutcome:
    return asyncio.run(
        consolidate_fact(
            text=text,
            kind=MemoryKind.SEMANTIC,
            confidence=1.0,
            source={"origin": "user_request"},
            store=store,
            embed_provider=provider,
            embed_model="m",
            judge_provider=provider,
            judge_model="m",
        )
    )


def test_adds_when_nothing_related() -> None:
    store = InMemoryMemoryStore()
    out = _consolidate(store, _Provider(None), "I am married to Viviana")
    assert out.op == "add" and out.item is not None
    assert len(asyncio.run(store.list())) == 1


def test_noop_on_a_duplicate_via_judge() -> None:
    store = InMemoryMemoryStore()
    provider = _Provider(json.dumps({"op": "noop"}))
    first = _consolidate(store, provider, "I am married to Viviana")
    assert first.op == "add"
    # Same text again -> the judge says noop -> nothing new stored.
    again = _consolidate(store, provider, "I am married to Viviana")
    assert again.op == "noop" and again.item is None
    assert len(asyncio.run(store.list())) == 1


def test_update_supersedes_the_contradicted_memory() -> None:
    store = InMemoryMemoryStore()
    add_provider = _Provider(None)
    first = _consolidate(store, add_provider, "I am married to Cotirlea")
    assert first.item is not None
    old_id = first.item.id

    # A contradicting fact: the judge points at the old memory and supplies the correction. Real
    # embeddings make "married to X" / "married to Y" similar; emulate that by mapping the new text
    # to the same one-hot vector as the stored memory so it is retrieved as related.
    judge = _Provider(
        json.dumps({"op": "update", "target_id": old_id, "text": "married to Cotillera"})
    )
    judge._idx = dict(add_provider._idx)  # noqa: SLF001 - keep the vector space aligned
    judge._idx["I am married to Cotillera"] = add_provider._idx["I am married to Cotirlea"]  # noqa: SLF001
    out = _consolidate(store, judge, "I am married to Cotillera")
    assert out.op == "update" and out.superseded_id == old_id

    visible = asyncio.run(store.list())  # superseded memory is hidden; only the correction remains
    assert len(visible) == 1
    assert visible[0].text == "married to Cotillera"


def test_invalid_target_id_falls_back_to_add() -> None:
    store = InMemoryMemoryStore()
    provider = _Provider(None)
    _consolidate(store, provider, "fact one")
    judge = _Provider(json.dumps({"op": "update", "target_id": "does-not-exist", "text": "x"}))
    judge._idx = provider._idx  # noqa: SLF001
    out = _consolidate(store, judge, "fact one")
    # Top match is a duplicate but the judge named a bogus id -> treated as add (not a crash).
    assert out.op == "add" and out.item is not None


def test_judge_failure_falls_back_to_dedup_only() -> None:
    store = InMemoryMemoryStore()
    provider = _Provider(None)  # generate() returns "not json" -> generate_structured returns None
    assert _consolidate(store, provider, "duplicate fact").op == "add"
    # Re-stating the same fact: judge unavailable, top score is a self-match (>= dedup) -> noop.
    again = _consolidate(store, provider, "duplicate fact")
    assert again.op == "noop" and again.item is None
    assert len(asyncio.run(store.list())) == 1
