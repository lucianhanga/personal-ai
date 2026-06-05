"""Port: retriever.

A retrieval strategy (vector, keyword, or graph/KAG) that, given a query, returns ranked
results **with citations** so answers remain explainable (ADR-0003, ADR-0005). Concrete
strategies live under ``retrieval/`` and are registered with the core (M0-4).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class RetrievalQuery:
    """A retrieval request."""

    text: str
    top_k: int = 5
    filters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Citation:
    """Where a retrieved item came from, for provenance/explainability."""

    source_id: str
    locator: str | None = None


@dataclass(frozen=True)
class RetrievedItem:
    """A single ranked retrieval result."""

    content: str
    score: float
    citation: Citation
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class Retriever(Protocol):
    """A strategy that retrieves ranked, cited items for a query."""

    name: str

    async def retrieve(self, query: RetrievalQuery) -> Sequence[RetrievedItem]:
        """Return ranked results for ``query`` (highest score first)."""
        ...
