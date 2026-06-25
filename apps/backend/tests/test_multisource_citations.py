"""Multi-source retrieval provenance (#420): the pure builders + the LangChain->item adapter.

Covers the module-level helpers that turn the merge node's unified citations into per-source
retrieval prelude items and per-source context-breakdown groups, and the non-LangChain
``VectorItemRetriever`` adapter that lets the core ``VectorSource`` wrap the hybrid retriever
without importing langchain. The end-to-end emit/persist through ``/api/v1/chat`` needs Postgres and
lives behind the DB skip; these run everywhere.
"""

from __future__ import annotations

import asyncio

from langchain_core.documents import Document

from personalai_backend.app import (
    _add_source_kind_breakdown,
    _per_source_retrieval_items,
)
from personalai_backend.rag.retriever import VectorItemRetriever, _document_to_item
from personalai_contracts.ports import SOURCE_KIND_MEMORY, SOURCE_KIND_VECTOR, RetrievalQuery


def _cites() -> list[dict[str, object]]:
    return [
        {
            "n": 1,
            "source_id": "doc-1",
            "locator": "chunk 0",
            "score": 0.5,
            "name": "report.pdf",
            "source_kind": SOURCE_KIND_VECTOR,
            "merged_from": [],
        },
        {
            "n": 2,
            "source_id": "doc-2",
            "locator": "chunk 3",
            "score": 0.4,
            "name": "notes.md",
            "source_kind": SOURCE_KIND_VECTOR,
            "merged_from": [],
        },
        {
            "n": 3,
            "source_id": "memory:1",
            "locator": "preference",
            "score": 0.3,
            "name": "Memory",
            "source_kind": SOURCE_KIND_MEMORY,
            "merged_from": [],
        },
    ]


def test_per_source_retrieval_items_groups_by_kind() -> None:
    items = _per_source_retrieval_items(_cites(), query="q", top_k=8, scope="union")
    by_kind = {it["source_kind"]: it for it in items}
    assert set(by_kind) == {SOURCE_KIND_VECTOR, SOURCE_KIND_MEMORY}
    assert by_kind[SOURCE_KIND_VECTOR]["hits"] == 2  # two vector citations grouped
    assert by_kind[SOURCE_KIND_MEMORY]["hits"] == 1
    assert by_kind[SOURCE_KIND_VECTOR]["kind"] == "retrieval"
    assert "(vector)" in by_kind[SOURCE_KIND_VECTOR]["text"]


def test_per_source_retrieval_items_empty_when_no_citations() -> None:
    assert _per_source_retrieval_items([], query="q", top_k=8, scope="global") == []


def test_add_source_kind_breakdown_appends_per_kind_rows() -> None:
    breakdown: dict[str, object] = {
        "items": [{"label": "Documents", "count": 1, "chars": 10, "text": "x"}],
        "total_chars": 10,
    }
    _add_source_kind_breakdown(breakdown, _cites())
    labels = [it["label"] for it in breakdown["items"]]  # type: ignore[union-attr]
    assert "Documents (vector)" in labels
    assert "Memory" in labels
    # The original item is preserved (additive), and totals grow.
    assert "Documents" in labels
    assert breakdown["total_chars"] > 10


def test_document_to_item_maps_citation_metadata() -> None:
    doc = Document(
        page_content="chunk text",
        metadata={
            "citation": {
                "source_id": "doc-9",
                "locator": "chunk 2",
                "name": "file.pdf",
                "score": 0.77,
            }
        },
    )
    item = _document_to_item(doc)
    assert item.content == "chunk text"
    assert item.citation.source_id == "doc-9"
    assert item.citation.locator == "chunk 2"
    assert item.score == 0.77
    assert item.metadata["name"] == "file.pdf"


class _FakeInner:
    """A stand-in for HybridVectorStoreRetriever exposing the langchain ainvoke shape."""

    async def ainvoke(self, query: str):  # type: ignore[no-untyped-def]
        return [
            Document(
                page_content="hit",
                metadata={
                    "citation": {"source_id": "d1", "locator": None, "name": "d1", "score": 0.9}
                },
            )
        ]


def test_vector_item_retriever_adapts_documents_to_items() -> None:
    adapter = VectorItemRetriever(_FakeInner())  # type: ignore[arg-type]

    async def _run():  # type: ignore[no-untyped-def]
        return await adapter.retrieve(RetrievalQuery(text="q", top_k=5))

    items = asyncio.run(_run())
    assert len(items) == 1
    assert items[0].citation.source_id == "d1"
    assert items[0].content == "hit"
