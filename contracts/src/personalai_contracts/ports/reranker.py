"""Port: reranker — cross-encoder reranking of retrieved items (#492)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from personalai_contracts.ports.retriever import RetrievedItem


@runtime_checkable
class Reranker(Protocol):
    """Re-score a list of RetrievedItems against a query (highest score first)."""

    name: str

    async def rerank(
        self, query: str, items: Sequence[RetrievedItem], top_n: int | None = None
    ) -> Sequence[RetrievedItem]: ...
