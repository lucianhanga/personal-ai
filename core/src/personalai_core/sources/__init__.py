"""Multi-source retrieval (#420): the RAG vector store as ONE :class:`RetrievalSource` behind a
query-planner that also reaches memory (and, later, graph/tools), with evidence merged and grounded.

This package owns the orchestration-layer slice of the #420 design (the storage DDL and the
LangChain dependency surface live elsewhere):

* ``plan``   — heuristic-first source routing (vector+memory floored on; the model gates optionals).
* ``gather`` — bounded-parallel ``asyncio.gather`` over the planned sources under one step's guard.
* ``merge``  — cross-source dedup + RRF(k=60) + the first cross-source token budget (per-source
  floor).
* ``vector`` / ``memory`` / ``graph`` — the source conformances (graph is a deferred no-op stub).

Depends only on ``personalai_contracts`` (ADR-0001). LangChain stays an engine detail INSIDE the
vector source's wrapped retriever (constructed at the backend composition root), never here.
"""

from personalai_core.sources.gather import allocate_budgets, gather_sources
from personalai_core.sources.graph import GraphSource
from personalai_core.sources.memory import MemorySource
from personalai_core.sources.merge import (
    RRF_K,
    MergeResult,
    deserialize_evidence,
    estimate_tokens,
    merge_evidence,
    serialize_evidence,
)
from personalai_core.sources.plan import plan_sources
from personalai_core.sources.vector import VectorSource

__all__ = [
    "RRF_K",
    "GraphSource",
    "MemorySource",
    "MergeResult",
    "VectorSource",
    "allocate_budgets",
    "deserialize_evidence",
    "estimate_tokens",
    "gather_sources",
    "merge_evidence",
    "plan_sources",
    "serialize_evidence",
]
