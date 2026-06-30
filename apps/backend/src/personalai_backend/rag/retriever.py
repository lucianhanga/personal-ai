"""A ``langchain_core`` ``BaseRetriever`` over our hybrid, RLS-scoped ``vectors`` table (#420).

Wraps :meth:`VectorRepository.hybrid_query` (dense + lexical RRF, k=60) as a thin
``langchain_core`` retriever. Storage, RLS, the scope predicate, and citations all stay on our
seams (we do NOT use ``langchain-postgres``/PGVector): the retriever embeds the query through our
``ModelProvider`` seam (:class:`ProviderEmbeddings`) and returns ``Document`` objects whose metadata
carries the citation contract (``source_id``, ``locator``, ``name``, ``score``) that
``_retrieve_context`` already emits.

Never calls LangChain ``load()``/``loads()`` -- chunk text and metadata are LLM-influenced/untrusted
(CVE-2025-68664 class). We build ``Document`` objects directly from our own ``VectorMatch`` rows.
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from personalai_backend.rag.embeddings import ProviderEmbeddings
from personalai_contracts.ports import (
    Citation,
    Reranker,
    RetrievalQuery,
    RetrievedItem,
    VectorMatch,
    VectorRepository,
)
from personalai_contracts.ports.storage import GLOBAL_SCOPE, Scope

# A retrieval query is a question, not a document -- cap before embedding (#416/#431). Kept here at
# the retriever boundary in addition to ProviderEmbeddings so the cap holds regardless of caller.
_MAX_QUERY_CHARS = 2000


def _to_document(match: VectorMatch) -> Document:
    """Map a :class:`VectorMatch` to a ``Document`` carrying our citation metadata."""
    metadata = dict(match.metadata)
    chunk_index = metadata.get("chunk_index")
    # The citation contract _retrieve_context consumes: source_id + chunk locator + name + score.
    citation: dict[str, Any] = {
        "source_id": str(metadata.get("document_id", "")),
        "locator": None if chunk_index is None else f"chunk {chunk_index}",
        "name": metadata.get("name"),
        "score": float(match.score),
    }
    return Document(
        page_content=str(metadata.get("text", "")),
        metadata={**metadata, "citation": citation},
    )


class HybridVectorStoreRetriever(BaseRetriever):
    """A ``langchain_core`` retriever over PersonalAI's hybrid, scoped ``vectors`` table.

    Construct it bound to a scope (default: the global corpus). The scope is mandatory state -- the
    retriever cannot run without one -- and is passed straight through to ``hybrid_query`` so the
    anti-bleed / RLS guarantees of the storage layer are preserved (CISO P2).
    """

    # BaseRetriever is a Pydantic model; allow our (non-pydantic) port objects as fields.
    model_config = {"arbitrary_types_allowed": True}

    vectors: VectorRepository
    embeddings: ProviderEmbeddings
    top_k: int = 5
    scope: Scope = GLOBAL_SCOPE
    # When set, retrieval covers the UNION of the global corpus AND this conversation's ephemeral
    # attachments (#420 PR4: "global OR conversation_id = :cid"). Takes precedence over ``scope``
    # and is passed straight to ``hybrid_query`` so the storage layer enforces anti-bleed.
    union_conversation_id: str | None = None

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        # Cap then embed via our ModelProvider seam (NOT langchain-ollama), then run the single
        # dense+lexical RRF query honoring the bound scope (or the global+conversation union when
        # union_conversation_id is set). Empty embedding -> no results.
        embedding = await self.embeddings.aembed_query(query[:_MAX_QUERY_CHARS])
        if not embedding:
            return []
        matches = await self.vectors.hybrid_query(
            embedding,
            query[:_MAX_QUERY_CHARS],
            self.top_k,
            scope=self.scope,
            union_conversation_id=self.union_conversation_id,
        )
        return [_to_document(m) for m in matches]

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:  # pragma: no cover - the app path is always async
        raise NotImplementedError(
            "HybridVectorStoreRetriever is async-only; use ainvoke / _aget_relevant_documents"
        )


def _document_to_item(doc: Document) -> RetrievedItem:
    """Adapt a LangChain ``Document`` (carrying our citation metadata) back to a ``RetrievedItem``.

    This is the ADR-0012 boundary where the LangChain engine detail is converted to our own type:
    the multi-source ``VectorSource`` (core) wraps a :class:`VectorItemRetriever`, never a LangChain
    object, so nothing above the seam imports ``langchain_*``."""
    cite = doc.metadata.get("citation", {})
    return RetrievedItem(
        content=doc.page_content,
        score=float(cite.get("score", 0.0)),
        citation=Citation(source_id=str(cite.get("source_id", "")), locator=cite.get("locator")),
        metadata={"name": cite.get("name"), "text": doc.page_content},
    )


class VectorItemRetriever:
    """A thin, non-LangChain adapter: the hybrid retriever as ``retrieve -> RetrievedItem``s.

    The #420 multi-source ``VectorSource`` (in ``personalai_core``) needs a
    ``retrieve(RetrievalQuery) -> Sequence[RetrievedItem]`` (the existing ``Retriever`` shape), but
    :class:`HybridVectorStoreRetriever` is a LangChain ``BaseRetriever`` returning ``Document``s.
    This wraps it and adapts the output to our type at the boundary, keeping LangChain strictly
    inside the backend (ADR-0012). Scope / RLS / union anti-bleed are unchanged — they live in the
    wrapped LangChain retriever's ``hybrid_query`` call."""

    name = "vector"

    def __init__(self, inner: HybridVectorStoreRetriever) -> None:
        self._inner = inner

    async def retrieve(self, query: RetrievalQuery) -> list[RetrievedItem]:
        docs = await self._inner.ainvoke(query.text)
        return [_document_to_item(d) for d in docs]


async def rerank_documents(reranker: Reranker, query: str, docs: list[Document]) -> list[Document]:
    """Reorder hybrid-retrieval ``Document``s by a cross-encoder reranker (#492).

    Adapts each ``Document`` to a ``RetrievedItem`` at the ADR-0012 boundary, reranks, then maps
    the reranked items back to their source ``Document`` so the caller's citation/context building
    (which reads ``doc.metadata``) is unchanged -- only the order changes. The reranker returns the
    SAME item objects reordered, so identity mapping is exact. A reranker that slices (``top_n``)
    simply yields fewer documents. This is the single-agent-path counterpart to ``VectorSource``'s
    rerank step, so reranking applies to both retrieval paths when ``RERANK_ENABLED`` is set."""
    if not docs:
        return docs
    items = [_document_to_item(d) for d in docs]
    by_id = {id(item): doc for item, doc in zip(items, docs, strict=True)}
    ordered = await reranker.rerank(query, items)
    return [by_id[id(item)] for item in ordered]
