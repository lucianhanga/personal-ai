"""Aggressive NER (#465): extraction sweeps the WHOLE document via overlapping windows and merges
the per-window results, so an entity that only appears deep in a long document is still captured.
A fake provider returns one valid structured entity per window (named by call order), letting us
assert both whole-document coverage and the cross-window de-duplication."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from personalai_contracts.ports import GenerationChunk, GenerationRequest
from personalai_contracts.testing import FakeModelProvider
from personalai_core.entity_extraction import extract_entities


class _PerWindowNer(FakeModelProvider):
    """Returns a distinct org per call -> each window contributes its own entity."""

    def __init__(self) -> None:
        super().__init__(name="ner")
        self.calls = 0

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        self.calls += 1
        payload = json.dumps(
            {"entities": [{"type": "org", "name": f"vendor-{self.calls}"}], "relations": []}
        )
        yield GenerationChunk(delta=payload)
        yield GenerationChunk(done=True, finish_reason="stop")


class _ConstantNer(FakeModelProvider):
    """Returns the SAME entity every call -> windows merge to a single entity."""

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        payload = json.dumps({"entities": [{"type": "org", "name": "M-Net"}], "relations": []})
        yield GenerationChunk(delta=payload)
        yield GenerationChunk(done=True, finish_reason="stop")


def test_default_window_is_model_aware() -> None:
    # The MoE breaks on big windows -> small; dense models run faster on a big window.
    from personalai_core.entity_extraction import (
        _DENSE_WINDOW_CHARS,
        _MOE_WINDOW_CHARS,
        _default_window,
    )

    assert _default_window("qwen3.6:35b-a3b") == _MOE_WINDOW_CHARS
    assert _default_window("qwen3:14b") == _DENSE_WINDOW_CHARS
    assert _DENSE_WINDOW_CHARS > _MOE_WINDOW_CHARS


def test_single_window_one_pass() -> None:
    prov = _PerWindowNer()
    res = asyncio.run(extract_entities("short text", provider=prov, model="m", window=4000))
    assert prov.calls == 1
    assert [e.name for e in res.entities] == ["vendor-1"]


def test_whole_document_covered_via_windows() -> None:
    # Longer than one window -> multiple overlapping passes, each contributing a distinct entity.
    text = "x" * 9000
    prov = _PerWindowNer()
    res = asyncio.run(extract_entities(text, provider=prov, model="m", window=4000, overlap=250))
    assert prov.calls >= 2
    assert len(res.entities) == prov.calls  # every window's entity is kept


def test_repeated_entity_deduped_across_windows() -> None:
    text = "y" * 9000
    res = asyncio.run(
        extract_entities(text, provider=_ConstantNer(), model="m", window=4000, overlap=250)
    )
    assert [e.name for e in res.entities] == ["M-Net"]  # one canonical entity, not one-per-window


def test_max_windows_bounds_passes() -> None:
    text = "z" * 100_000
    prov = _PerWindowNer()
    asyncio.run(
        extract_entities(text, provider=prov, model="m", window=4000, overlap=250, max_windows=3)
    )
    assert prov.calls == 3  # capped, the tail is not swept
