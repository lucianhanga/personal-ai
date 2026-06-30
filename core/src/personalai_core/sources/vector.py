"""VectorSource: the RAG vector store as a :class:`RetrievalSource` (#420).

Wraps an existing :class:`Retriever` (the hybrid dense+lexical retriever — the backend's LangChain
adapter, or core's :class:`VectorRetriever`) and adapts its ``RetrievedItem``s to provenance-tagged
:class:`Evidence` with ``source_kind="vector"``. The within-vector RRF / hybrid fusion stays INSIDE
the wrapped retriever; this source never re-fuses it. The LangChain engine detail, when any, lives
in the wrapped retriever (ADR-0012) — this class imports no ``langchain_*``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from personalai_contracts.ports import (
    SOURCE_KIND_VECTOR,
    AgentContext,
    Evidence,
    Reranker,
    RetrievalQuery,
    RetrievedItem,
)
from personalai_core.sources.merge import estimate_tokens


@runtime_checkable
class _ItemRetriever(Protocol):
    """The structural shape VectorSource wraps: ``retrieve(query) -> Sequence[RetrievedItem]``.

    Deliberately narrower than the full :class:`Retriever` port (it does NOT require ``name: str``)
    so the backend's LangChain ``HybridVectorStoreRetriever`` — whose ``name`` is ``str | None``
    from ``BaseRetriever`` — conforms without a cast. The LangChain engine detail stays inside that
    wrapped retriever (ADR-0012); this source only needs its ``retrieve``."""

    async def retrieve(self, query: RetrievalQuery) -> Sequence[RetrievedItem]: ...


class VectorSource:
    """Adapt a hybrid/dense retriever to the multi-source :class:`RetrievalSource` seam."""

    kind = SOURCE_KIND_VECTOR

    def __init__(
        self,
        retriever: _ItemRetriever,
        *,
        top_k: int = 5,
        name: str = "vector",
        reranker: Reranker | None = None,
    ) -> None:
        self._retriever = retriever
        self._top_k = top_k
        self.name = name
        self._reranker = reranker

    async def select(self, query: str, ctx: AgentContext | None) -> float | None:
        # Vector is a cheap, always-on grounded source: no opinion -> the planner/heuristic floors
        # it.
        return None

    async def retrieve(
        self, query: str, budget: int, ctx: AgentContext | None
    ) -> Sequence[Evidence]:
        items = await self._retriever.retrieve(RetrievalQuery(text=query, top_k=self._top_k))
        if self._reranker is not None:
            items = await self._reranker.rerank(query, items)
        evidence: list[Evidence] = []
        spent = 0
        for item in items:
            cost = estimate_tokens(item.content)
            # Honor the merge-allocated budget defensively at the source boundary too (the merge
            # node is authoritative, but a source that respects its budget keeps gather bounded). A
            # non-positive budget means "no per-source cap" (the merge node does the trimming).
            if budget > 0 and spent + cost > budget and evidence:
                break
            evidence.append(
                Evidence(
                    text=item.content,
                    score=item.score,
                    citation=item.citation,
                    source_kind=SOURCE_KIND_VECTOR,
                    metadata=item.metadata,
                )
            )
            spent += cost
        return evidence
