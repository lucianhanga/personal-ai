"""In-process cross-encoder reranker via HuggingFace Transformers, Qwen3-Reranker-0.6B (#492).

Implements the :class:`Reranker` port with NO separate server: the model is downloaded once from
HuggingFace (then cached and usable offline) and runs in-process. The model is heavy to load, so
a single instance per model name is cached and reused; the blocking inference runs in a worker
thread so it never stalls the event loop.

Design decisions:
- On-demand load: no model footprint when the rerank flag is off.
- Module-level cache keyed by model name: weights load once per process, subsequent calls are fast.
- Half-precision (float16) inference: halves memory vs. float32, fine for ranking (not generation).
- ``asyncio.to_thread``: the forward pass is CPU/GPU-bound; running it off the event loop keeps
  FastAPI responsive during reranking.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from personalai_contracts.ports.retriever import RetrievedItem

# On-demand-but-cached model instances, keyed by model name.
_MODELS: dict[str, tuple[Any, Any]] = {}


def _load_model(model: str, device: str) -> tuple[Any, Any]:
    """Load (tokenizer, model) from HuggingFace and cache by model name.

    The import of ``transformers`` and ``torch`` is deferred until the first call so that the
    heavy dependency is only pulled in when reranking is actually used (flag-gated).
    """
    cached = _MODELS.get(model)
    if cached is not None:
        return cached

    import torch  # noqa: PLC0415
    from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: PLC0415

    _device = ("cuda" if torch.cuda.is_available() else "cpu") if device == "auto" else device

    tokenizer = AutoTokenizer.from_pretrained(model)
    loaded_model = (
        AutoModelForSequenceClassification.from_pretrained(model, torch_dtype=torch.float16)
        .to(_device)
        .eval()
    )
    result = (tokenizer, loaded_model)
    _MODELS[model] = result
    return result


class HFReranker:
    """A :class:`Reranker` running a cross-encoder in-process via HuggingFace Transformers.

    The model is loaded on first use (on-demand) and cached for the lifetime of the process.
    All CPU/GPU-bound inference runs in a worker thread via ``asyncio.to_thread``.
    """

    name = "hf-reranker"

    def __init__(
        self,
        *,
        model: str = "Qwen/Qwen3-Reranker-0.6B",
        top_n: int | None = None,
        device: str = "auto",
    ) -> None:
        self._model = model
        self._top_n = top_n
        self._device = device

    def _rerank_sync(self, query: str, texts: list[str]) -> list[float]:
        """Tokenize (query, passage) pairs, run the cross-encoder, return per-item scores.

        Scores are raw logits from the classification head — suitable for relative ranking
        (higher = more relevant). Sigmoid / calibration is intentionally skipped because
        downstream callers only need ordinal ranking, not calibrated probabilities.
        """
        import torch  # noqa: PLC0415

        if not texts:
            return []

        tokenizer, model = _load_model(self._model, self._device)
        inputs = tokenizer(
            [query] * len(texts),
            texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512,
        ).to(model.device)

        with torch.no_grad():
            outputs = model(**inputs)

        # Qwen3-Reranker has a single-class head: logits shape [N, 1] or [N].
        # .squeeze(-1) normalises both shapes to a flat [N] tensor before converting to Python list.
        scores: list[float] = outputs.logits.squeeze(-1).float().tolist()
        # Ensure a list even when only one item was passed (squeeze collapses to a scalar).
        if not isinstance(scores, list):
            scores = [scores]
        return scores

    async def rerank(
        self,
        query: str,
        items: Sequence[RetrievedItem],
        top_n: int | None = None,
    ) -> Sequence[RetrievedItem]:
        """Re-score ``items`` against ``query`` and return them sorted highest-score-first.

        The forward pass runs in a worker thread so the event loop stays unblocked.
        ``top_n`` (or ``self._top_n`` when ``top_n`` is not given) slices the result; omit both to
        return all items re-ranked.
        """
        if not items:
            return items

        texts = [item.content for item in items]
        scores = await asyncio.to_thread(self._rerank_sync, query, texts)

        scored = sorted(zip(scores, items, strict=True), key=lambda t: t[0], reverse=True)
        reranked = [item for _, item in scored]

        limit = top_n if top_n is not None else self._top_n
        if limit is not None:
            reranked = reranked[:limit]
        return reranked
