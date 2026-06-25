"""Port: retriever.

A retrieval strategy (vector, keyword, or graph/KAG) that, given a query, returns ranked
results **with citations** so answers remain explainable (ADR-0003, ADR-0005). Concrete
strategies live under ``retrieval/`` and are registered with the core (M0-4).

#420 multi-source: the single-strategy :class:`Retriever` widens into a :class:`RetrievalSource` —
a *sibling* a query-planner can select and an evidence-merge node can fuse. A source returns
provenance-tagged :class:`Evidence` (``RetrievedItem`` + ``source_kind`` + ``merged_from``) so
vector / memory / graph(KAG) / tool results are mergeable under one cross-source ranking. The seam
stays OURS (ADR-0012): a LangChain retriever, when used, lives *inside* a source and is adapted to
:class:`Evidence` at the boundary — nothing above this port imports ``langchain_*``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from personalai_contracts.ports.agent import AgentContext


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


# ---------------------------------------------------------------------------
# #420 multi-source retrieval: Evidence + the RetrievalSource seam.
# ---------------------------------------------------------------------------

# The known source kinds. Tool sources carry a suffix ("tool:web_search", "tool:mcp:<srv>"); the
# constants name the always-on cheap sources + the deferred graph(KAG) stub. Kept as plain strings
# (not a StrEnum) so a "tool:<name>" kind composes without a closed enum and serializes trivially
# into the citation dict the UI already consumes.
SOURCE_KIND_VECTOR = "vector"
SOURCE_KIND_MEMORY = "memory"
SOURCE_KIND_GRAPH = "graph"


@dataclass(frozen=True)
class Evidence:
    """A provenance-tagged retrieval result that is mergeable across sources (#420).

    ``Evidence`` is :class:`RetrievedItem` + ``source_kind`` (and ``merged_from`` for cross-source
    dedup), kept a DISTINCT type rather than extending ``RetrievedItem`` so the existing
    single-source vector path is untouched and ``source_kind`` never leaks into it. ``score`` is the
    source-LOCAL score — NOT comparable across sources; the merge node re-ranks by cross-source RRF
    (rank-based) and never compares these raw scores. ``merged_from`` records the other source kinds
    a deduped item also appeared in, so one ``[n]`` can honestly attribute a fact to several
    sources.
    """

    text: str
    score: float
    citation: Citation
    source_kind: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    merged_from: tuple[str, ...] = ()


@runtime_checkable
class RetrievalSource(Protocol):
    """A pluggable retrieval source the query-planner selects and the merge node fuses (#420).

    Widens :class:`Retriever`: ``retrieve`` returns provenance-tagged :class:`Evidence` under a
    *token* ``budget`` the merge node allocated to this source, and ``select`` is an OPTIONAL cheap
    applicability signal (0..1; ``None`` = "let the planner decide"). Concrete sources wrap existing
    seams (vector -> the hybrid ``Retriever``; memory -> ``recall``; graph -> a deferred no-op stub;
    tool -> the ``run_agent``/``ToolGateway`` path) and adapt their output to ``Evidence`` — the
    LangChain/engine detail, when any, stays INSIDE the source (ADR-0012).
    """

    name: str
    kind: str

    async def select(self, query: str, ctx: AgentContext | None) -> float | None:
        """An optional cheap relevance/applicability score in ``[0, 1]`` for the planner. ``None``
        means "no opinion — let the planner/heuristic decide" (the default for cheap always-on
        sources)."""
        ...

    async def retrieve(
        self, query: str, budget: int, ctx: AgentContext | None
    ) -> Sequence[Evidence]:
        """Return ranked :class:`Evidence` for ``query``, bounded by the token ``budget`` the merge
        node allocated to this source (highest source-local score first)."""
        ...
