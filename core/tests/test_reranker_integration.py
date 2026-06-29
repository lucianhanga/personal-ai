"""VectorSource reranker integration tests (#492).

Verifies that the optional reranker slot in VectorSource works correctly:
- When no reranker is provided (``reranker=None``), items are returned in the original retrieval
  score order and no reranker is ever invoked.
- When a reranker is injected, its output ordering is reflected in the returned Evidence sequence.

All fakes are defined here; no HuggingFace or heavy dependencies are required.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from personalai_contracts.ports import Citation, RetrievalQuery, RetrievedItem
from personalai_core.sources.vector import VectorSource

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeRetriever:
    """Returns two items with fixed content and scores (first > second)."""

    async def retrieve(self, query: RetrievalQuery) -> Sequence[RetrievedItem]:
        return [
            RetrievedItem(content="alpha", score=0.9, citation=Citation(source_id="a")),
            RetrievedItem(content="beta", score=0.5, citation=Citation(source_id="b")),
        ]


class _ReversingReranker:
    """A fake reranker that reverses the order of items (beta before alpha).

    Assigns new descending scores so the last item in the input becomes the highest-scored
    output, verifying that VectorSource uses the reranker's returned ordering rather than the
    original retriever ordering.
    """

    name = "fake-reversing-reranker"
    call_count: int = 0

    async def rerank(
        self, query: str, items: Sequence[RetrievedItem], top_n: int | None = None
    ) -> Sequence[RetrievedItem]:
        self.call_count += 1
        reversed_items = list(reversed(items))
        rescored = [
            RetrievedItem(
                content=item.content,
                score=float(len(reversed_items) - i),
                citation=item.citation,
                metadata=item.metadata,
            )
            for i, item in enumerate(reversed_items)
        ]
        return rescored


class _SpyReranker:
    """A reranker that records calls; used to verify it is never invoked when flag is off."""

    name = "fake-spy-reranker"
    call_count: int = 0

    async def rerank(
        self, query: str, items: Sequence[RetrievedItem], top_n: int | None = None
    ) -> Sequence[RetrievedItem]:
        self.call_count += 1
        return list(items)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_rerank_not_called_when_reranker_none() -> None:
    """VectorSource with no reranker returns Evidence in original retrieval score order."""

    async def _run() -> None:
        source = VectorSource(_FakeRetriever(), top_k=5)
        results = await source.retrieve("query", budget=0, ctx=None)
        assert len(results) == 2
        # Original order: alpha first (higher retriever score), beta second.
        assert results[0].text == "alpha"
        assert results[1].text == "beta"

    asyncio.run(_run())


def test_rerank_reorders_items() -> None:
    """A reranker that reverses order is reflected in the Evidence sequence from VectorSource."""

    async def _run() -> None:
        reranker = _ReversingReranker()
        source = VectorSource(_FakeRetriever(), top_k=5, reranker=reranker)
        results = await source.retrieve("query", budget=0, ctx=None)
        # The reversing reranker should put beta before alpha.
        assert len(results) == 2
        assert results[0].text == "beta", (
            f"Expected 'beta' first after reranking, got '{results[0].text}'"
        )
        assert results[1].text == "alpha"
        # Confirm the reranker was actually called once.
        assert reranker.call_count == 1

    asyncio.run(_run())


def test_rerank_flag_off_bypass() -> None:
    """VectorSource(reranker=None).retrieve() never invokes any reranker."""

    async def _run() -> None:
        spy = _SpyReranker()
        # Pass reranker=None explicitly — the spy must never be called.
        source = VectorSource(_FakeRetriever(), top_k=5, reranker=None)
        results = await source.retrieve("query", budget=0, ctx=None)
        assert spy.call_count == 0, "Reranker must not be called when reranker=None"
        # Results still arrive (original order).
        assert len(results) == 2
        assert results[0].text == "alpha"

    asyncio.run(_run())
