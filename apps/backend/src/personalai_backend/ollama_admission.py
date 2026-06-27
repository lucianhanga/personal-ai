"""Memory-aware admission control for the local NER model (#464).

Ollama is SHARED -- other processes may have models loaded too -- so before we trigger a NER model
load we check the GLOBAL load (``/api/ps``) against a memory budget (a fraction of total system
memory) and only proceed if the model is already resident OR fits WITHOUT evicting anything.
Otherwise we DEFER (raise :class:`AdmissionDeferred`) so the caller can retry later and signal the
user -- we never gamble on evicting a model another process might be using.

This gate's only job is to avoid an out-of-memory *load* (the crash we hit loading a big model at a
large context). It does NOT need to protect in-flight work: Ollama's server-side ``refCount`` won't
evict a model with a request running, for every process. Best-effort: if memory can't be
measured or Ollama is unreachable, it does not block (the real call then surfaces any error).
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

# KV-cache bytes per element by Ollama's OLLAMA_KV_CACHE_TYPE. We estimate with f16 (the default and
# the largest) so the estimate is conservative even if the server is configured with q8_0/q4_0.
_KV_BYTES_PER_ELEMENT = {"f16": 2.0, "q8_0": 1.0, "q4_0": 0.5}
_WEIGHTS_OVERHEAD = 1.10  # quantized weight file -> resident, plus alloc overhead
_FIXED_OVERHEAD_BYTES = 512 * 1024 * 1024  # graph/runtime fixed cost


class AdmissionDeferred(RuntimeError):
    """Not enough free memory to load the NER model right now; the caller should retry later."""


def _total_ram_bytes() -> int:
    """Total physical memory, cross-platform (Linux + macOS) via sysconf. 0 if unknown."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):  # pragma: no cover - platform without sysconf
        return 0


def _model_info_int(info: dict[str, object], suffix: str) -> int:
    """Read an architecture int from /api/show model_info by key suffix (the prefix is arch-
    specific, e.g. ``llama.block_count`` vs ``qwen3.block_count``)."""
    for key, value in info.items():
        if key.endswith(suffix) and isinstance(value, int):
            return value
    return 0


def _kv_cache_bytes(info: dict[str, object], num_ctx: int, kv_type: str) -> int:
    layers = _model_info_int(info, ".block_count")
    kv_heads = _model_info_int(info, ".attention.head_count_kv")
    heads = _model_info_int(info, ".attention.head_count")
    embed = _model_info_int(info, ".embedding_length")
    if not (layers and kv_heads and heads and embed):
        return 0
    head_dim = embed // heads
    per = _KV_BYTES_PER_ELEMENT.get(kv_type, 2.0)
    return int(2 * layers * kv_heads * head_dim * num_ctx * per)


async def assert_ner_admission(
    *,
    base_url: str,
    model: str,
    num_ctx: int,
    memory_fraction: float,
    kv_type: str = "f16",
    timeout: float = 15.0,
) -> None:
    """Raise :class:`AdmissionDeferred` if loading ``model`` would not fit within
    ``memory_fraction`` of total RAM given the CURRENT global Ollama load. No-ops (admits) when the
    model is already resident, or when memory / Ollama state can't be read (best-effort)."""
    total = _total_ram_bytes()
    if total <= 0:
        return  # can't measure -> don't block
    budget = int(total * memory_fraction)
    base = base_url.rstrip("/")

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        try:
            ps = (await client.get(f"{base}/api/ps")).json().get("models", [])
        except (httpx.HTTPError, ValueError):
            return  # Ollama unreachable -> let the real generate call surface the error
        used = sum(int(m.get("size_vram", 0) or 0) for m in ps)
        if any(m.get("name") == model for m in ps):
            return  # already resident -> reuse, no new allocation

        weights = 0
        try:
            tags = (await client.get(f"{base}/api/tags")).json().get("models", [])
            weights = next((int(m.get("size", 0) or 0) for m in tags if m.get("name") == model), 0)
        except (httpx.HTTPError, ValueError):
            weights = 0
        kv = 0
        try:
            show = (await client.post(f"{base}/api/show", json={"model": model})).json()
            kv = _kv_cache_bytes(show.get("model_info") or {}, num_ctx, kv_type)
        except (httpx.HTTPError, ValueError):
            kv = 0

        footprint = int(weights * _WEIGHTS_OVERHEAD) + kv + _FIXED_OVERHEAD_BYTES
        available = budget - used
        if footprint <= available:
            return  # fits within budget without evicting anything

        raise AdmissionDeferred(
            f"NER model {model!r} needs ~{footprint / 1e9:.1f}GB but only "
            f"~{max(0, available) / 1e9:.1f}GB free within the {memory_fraction:.0%} budget "
            f"({budget / 1e9:.1f}GB of {total / 1e9:.1f}GB; {used / 1e9:.1f}GB in use by Ollama). "
            f"Deferring -- will retry on the next pass."
        )
