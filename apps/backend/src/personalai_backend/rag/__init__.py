"""LangChain-core RAG adapters (ADR-0012, #420 Phase 0 PR2).

Thin adapters that expose PersonalAI's hybrid (dense + lexical RRF) scoped retrieval through the
``langchain_core`` interfaces, WITHOUT moving storage, RLS, the scope predicate, the embeddings
seam, or citations onto LangChain:

* :class:`ProviderEmbeddings` wraps our ``ModelProvider.embed`` seam as a ``langchain_core``
  ``Embeddings`` (never ``langchain-ollama``).
* :class:`HybridVectorStoreRetriever` is a ``langchain_core`` ``BaseRetriever`` over the
  RLS-scoped ``vectors`` table via ``VectorRepository.hybrid_query`` (never ``langchain-postgres``),
  returning ``Document`` objects that carry our citation metadata.
* :func:`disable_langchain_tracing` force-disables LangSmith/LangChain tracing at startup (the
  in-process egress guard does not contain ``langsmith``'s own client).

This package is the OUTER (composition) layer: it depends on ``langchain-core`` plus our ports, so
it must NOT live in ``personalai_core``/``personalai_contracts`` (CISO review #420, ADR-0012).
"""

from __future__ import annotations

from personalai_backend.rag.embeddings import ProviderEmbeddings
from personalai_backend.rag.retriever import (
    HybridVectorStoreRetriever,
    VectorItemRetriever,
    rerank_documents,
)
from personalai_backend.rag.tracing import disable_langchain_tracing

__all__ = [
    "HybridVectorStoreRetriever",
    "ProviderEmbeddings",
    "VectorItemRetriever",
    "disable_langchain_tracing",
    "rerank_documents",
]
