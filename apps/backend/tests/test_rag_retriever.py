"""Unit tests for the langchain-core RAG adapters (#420 PR2) -- no DB, no model, no network.

Covers the adapter contract that the DB-gated hybrid tests cannot: the langchain-core retriever
maps our VectorMatch rows to Documents carrying the citation contract, applies the #431 query-length
cap BEFORE embedding, and keeps retrieval on the global scope. Uses fakes for the ModelProvider and
VectorRepository ports so it runs anywhere.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from langchain_core.documents import Document

from personalai_backend.rag import (
    HybridVectorStoreRetriever,
    ProviderEmbeddings,
    rerank_documents,
)
from personalai_contracts.ports import EmbeddingResult, RetrievedItem, VectorMatch
from personalai_contracts.ports.storage import GLOBAL_SCOPE, Scope
from personalai_contracts.testing import FakeModelProvider, InMemoryVectorRepository


class _RecordingProvider(FakeModelProvider):
    """A complete ModelProvider that also records the texts it was asked to embed."""

    def __init__(self) -> None:
        super().__init__()
        self.embedded: list[str] = []

    async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
        self.embedded.extend(texts)
        return await super().embed(texts, model)


class _RecordingVectors(InMemoryVectorRepository):
    """A complete VectorRepository whose hybrid_query records its args and returns fixtures."""

    def __init__(self, matches: Sequence[VectorMatch]) -> None:
        super().__init__()
        self._matches = list(matches)
        self.last_text: str | None = None
        self.last_scope: Scope | None = None
        self.last_top_k: int | None = None
        self.last_union_conversation_id: str | None = None

    async def hybrid_query(
        self,
        vector: Sequence[float],
        text: str,
        top_k: int = 5,
        *,
        scope: Scope = GLOBAL_SCOPE,
        union_conversation_id: str | None = None,
    ) -> Sequence[VectorMatch]:
        self.last_text = text
        self.last_scope = scope
        self.last_top_k = top_k
        self.last_union_conversation_id = union_conversation_id
        return self._matches


def _build(
    matches: Sequence[VectorMatch],
) -> tuple[HybridVectorStoreRetriever, _RecordingVectors, _RecordingProvider]:
    provider = _RecordingProvider()
    vectors = _RecordingVectors(matches)
    retriever = HybridVectorStoreRetriever(
        vectors=vectors,
        embeddings=ProviderEmbeddings(provider, "embed-model"),
        top_k=4,
    )
    return retriever, vectors, provider


def test_retriever_preserves_citation_metadata() -> None:
    """Each Document carries source_id, chunk locator, name, and score for the citation contract."""
    matches = [
        VectorMatch(
            id="v1",
            score=0.42,
            metadata={
                "text": "the answer is 42",
                "document_id": "doc-1",
                "chunk_index": 3,
                "name": "guide.pdf",
            },
        )
    ]
    retriever, _, _ = _build(matches)
    docs = asyncio.run(retriever.ainvoke("what is the answer"))

    assert len(docs) == 1
    doc = docs[0]
    assert doc.page_content == "the answer is 42"
    citation = doc.metadata["citation"]
    assert citation["source_id"] == "doc-1"
    assert citation["locator"] == "chunk 3"
    assert citation["name"] == "guide.pdf"
    assert citation["score"] == 0.42


def test_retriever_handles_missing_chunk_index_and_name() -> None:
    """A match with no chunk_index/name yields a null locator/name -- citations stay resilient."""
    matches = [VectorMatch(id="v1", score=0.1, metadata={"text": "x", "document_id": "doc-9"})]
    retriever, _, _ = _build(matches)
    docs = asyncio.run(retriever.ainvoke("q"))
    citation = docs[0].metadata["citation"]
    assert citation["locator"] is None
    assert citation["name"] is None
    assert citation["source_id"] == "doc-9"


def test_retriever_caps_query_length_before_embedding() -> None:
    """The #431 cap: an over-long query (e.g. polluted with folded document text) is truncated to
    2000 chars BEFORE it reaches the embedder AND before it reaches the lexical arm."""
    long_query = "a" * 5000
    retriever, vectors, provider = _build(
        [VectorMatch(id="v1", score=0.5, metadata={"text": "t", "document_id": "d"})]
    )
    asyncio.run(retriever.ainvoke(long_query))

    # The text handed to embed and to the lexical arm is capped at 2000 chars.
    assert provider.embedded == ["a" * 2000]
    assert vectors.last_text == "a" * 2000


def test_retriever_stays_on_global_scope() -> None:
    """PR2 keeps RAG global: the retriever passes global scope to hybrid_query (scope is PR4)."""
    retriever, vectors, _ = _build(
        [VectorMatch(id="v1", score=0.5, metadata={"text": "t", "document_id": "d"})]
    )
    asyncio.run(retriever.ainvoke("q"))
    assert vectors.last_scope is not None
    assert vectors.last_scope.is_global
    assert vectors.last_top_k == 4


def test_retriever_returns_empty_when_no_embedding() -> None:
    """No embedding vectors -> no retrieval call, empty result (mirrors VectorRetriever)."""

    class _EmptyProvider(_RecordingProvider):
        async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
            return EmbeddingResult(vectors=[], model=model, dimensions=0)

    vectors = _RecordingVectors([VectorMatch(id="v1", score=1.0, metadata={})])
    retriever = HybridVectorStoreRetriever(
        vectors=vectors, embeddings=ProviderEmbeddings(_EmptyProvider(), "m"), top_k=4
    )
    docs = asyncio.run(retriever.ainvoke("q"))
    assert docs == []
    assert vectors.last_text is None  # hybrid_query never called


# --- rerank_documents (#492): the single-agent-path counterpart to VectorSource's rerank step ---


class _FakeReranker:
    """A Reranker that reorders items by a content->score map (highest first) and records calls."""

    name = "fake"

    def __init__(self, scores: dict[str, float]) -> None:
        self._scores = scores
        self.calls: list[str] = []

    async def rerank(
        self, query: str, items: Sequence[RetrievedItem], top_n: int | None = None
    ) -> Sequence[RetrievedItem]:
        self.calls.append(query)
        ordered = sorted(items, key=lambda it: self._scores.get(it.content, 0.0), reverse=True)
        return ordered if top_n is None else ordered[:top_n]


def _doc(text: str, score: float) -> Document:
    return Document(
        page_content=text,
        metadata={"citation": {"source_id": text, "locator": "l", "score": score, "name": text}},
    )


def test_rerank_documents_reorders_by_reranker_score() -> None:
    # Vector order is a, b, c; the reranker prefers b, c, a.
    docs = [_doc("a", 0.9), _doc("b", 0.1), _doc("c", 0.5)]
    rr = _FakeReranker({"a": 0.0, "b": 1.0, "c": 0.5})
    out = asyncio.run(rerank_documents(rr, "q", docs))
    assert [d.page_content for d in out] == ["b", "c", "a"]
    assert rr.calls == ["q"]
    # The reranked list holds the ORIGINAL Document instances, just reordered (identity preserved),
    # so the caller's citation/context building over doc.metadata is unchanged.
    assert out[0] is docs[1] and out[1] is docs[2] and out[2] is docs[0]


def test_rerank_documents_empty_is_noop() -> None:
    rr = _FakeReranker({})
    assert asyncio.run(rerank_documents(rr, "q", [])) == []
    assert rr.calls == []  # never invoked on empty input (no warm load triggered)
