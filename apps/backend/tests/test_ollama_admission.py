"""Memory-aware NER admission control (#464): the KV/footprint math and the admit/defer decision,
with a fake Ollama client so no server or model is needed."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from personalai_backend import ollama_admission as oa

# A representative dense-model model_info (qwen3:14b-ish): 40 layers, 8 KV heads, 40 heads, 5120 d.
_ARCH: dict[str, object] = {
    "a.block_count": 40,
    "a.attention.head_count_kv": 8,
    "a.attention.head_count": 40,
    "a.embedding_length": 5120,
}


def test_model_info_int_reads_by_suffix() -> None:
    info = {"qwen3.block_count": 40, "qwen3.attention.head_count_kv": 8, "general.name": "x"}
    assert oa._model_info_int(info, ".block_count") == 40
    assert oa._model_info_int(info, ".attention.head_count_kv") == 8
    assert oa._model_info_int(info, ".missing") == 0


def test_kv_cache_bytes_formula() -> None:
    # head_dim = 5120/40 = 128; f16 -> 2 bytes/elem.
    assert oa._kv_cache_bytes(_ARCH, 8192, "f16") == 2 * 40 * 8 * 128 * 8192 * 2
    assert oa._kv_cache_bytes(_ARCH, 8192, "q8_0") == 2 * 40 * 8 * 128 * 8192 * 1
    assert oa._kv_cache_bytes({}, 8192, "f16") == 0  # missing arch -> 0


class _Resp:
    def __init__(self, data: dict[str, Any]) -> None:
        self._d = data

    def json(self) -> dict[str, Any]:
        return self._d


class _FakeClient:
    def __init__(self, ps: list[Any], tags: list[Any], show: dict[str, Any]) -> None:
        self._ps, self._tags, self._show = ps, tags, show

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False

    async def get(self, url: str) -> _Resp:
        if url.endswith("/api/ps"):
            return _Resp({"models": self._ps})
        if url.endswith("/api/tags"):
            return _Resp({"models": self._tags})
        raise AssertionError(url)

    async def post(self, url: str, json: Any = None) -> _Resp:
        if url.endswith("/api/show"):
            return _Resp({"model_info": self._show})
        raise AssertionError(url)


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    total: int,
    ps: list[Any],
    tags: list[Any],
    show: dict[str, Any],
) -> None:
    monkeypatch.setattr(oa, "_total_ram_bytes", lambda: total)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeClient(ps, tags, show))


def _run(**kw: Any) -> None:
    asyncio.run(
        oa.assert_ner_admission(
            base_url="http://x", model="qwen3:14b", num_ctx=8192, memory_fraction=0.75, **kw
        )
    )


def test_admits_when_model_already_resident(monkeypatch: pytest.MonkeyPatch) -> None:
    # Already loaded -> reuse, no new allocation, admit regardless of how full memory is.
    _patch(
        monkeypatch,
        total=48 * 10**9,
        ps=[{"name": "qwen3:14b", "size_vram": 10**10}, {"name": "other", "size_vram": 30 * 10**9}],
        tags=[],
        show={},
    )
    _run()  # no raise


def test_admits_when_it_fits(monkeypatch: pytest.MonkeyPatch) -> None:
    # budget = 36GB, used = 5GB -> ~31GB free; footprint ~10GB -> fits.
    _patch(
        monkeypatch,
        total=48 * 10**9,
        ps=[{"name": "other", "size_vram": 5 * 10**9}],
        tags=[{"name": "qwen3:14b", "size": 9_300_000_000}],
        show=_ARCH,
    )
    _run()  # no raise


def test_defers_when_no_room(monkeypatch: pytest.MonkeyPatch) -> None:
    # budget = 36GB, another process holds 34GB -> ~2GB free; NER footprint ~10GB -> defer.
    _patch(
        monkeypatch,
        total=48 * 10**9,
        ps=[{"name": "other", "size_vram": 34 * 10**9}],
        tags=[{"name": "qwen3:14b", "size": 9_300_000_000}],
        show=_ARCH,
    )
    with pytest.raises(oa.AdmissionDeferred):
        _run()


def test_no_block_when_memory_unmeasurable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Can't read total RAM -> best-effort admit (don't block).
    monkeypatch.setattr(oa, "_total_ram_bytes", lambda: 0)
    _run()  # no raise, no network touched
