"""Tier-2 ingest-at-send + union retrieval (#420 PR4 / #436) -- fakes only, no DB, no live model.

Exercises the real ``ingest_text`` pipeline + the real ``HybridVectorStoreRetriever`` against the
in-memory ``InMemoryVectorRepository`` (whose scope filter is the faithful analogue of the Postgres
union predicate). Proves:
  * a large attached doc ingested into conversation A is retrievable via A's union;
  * ANTI-BLEED: it is NOT retrievable from conversation B, nor from a no-conversation global query;
  * the global corpus stays retrievable alongside the attachment in A's union;
  * idempotent re-ingest (same content-hash id) creates no duplicate vectors;
  * the request-boundary helpers cap/validate the ingest text and derive a stable,
    conversation-keyed document id.
"""

from __future__ import annotations

import asyncio

from langchain_core.documents import Document

from personalai_backend.app import (
    _INGEST_TEXT_CAP,
    _MAX_INGEST_DOCS_PER_TURN,
    _conversation_document_id,
    _ingest_docs_from_turn,
)
from personalai_backend.ingestion import ingest_text
from personalai_backend.rag import HybridVectorStoreRetriever, ProviderEmbeddings
from personalai_contracts.ports.storage import GLOBAL_SCOPE, Scope
from personalai_contracts.testing import FakeModelProvider, InMemoryVectorRepository

EMBED_MODEL = "fake-embed"


def _retriever(
    vectors: InMemoryVectorRepository, *, union_conversation_id: str | None
) -> HybridVectorStoreRetriever:
    return HybridVectorStoreRetriever(
        vectors=vectors,
        embeddings=ProviderEmbeddings(FakeModelProvider(), EMBED_MODEL),
        top_k=10,
        union_conversation_id=union_conversation_id,
    )


def _ids(docs: list[Document]) -> set[str]:
    return {str(d.metadata.get("document_id")) for d in docs}


def test_large_doc_retrievable_in_its_conversation_not_in_another() -> None:
    """The headline tier-2 flow + the anti-bleed HARD gate, end to end through real ingest +
    retriever code against the in-memory store."""

    async def _run() -> None:
        vectors = InMemoryVectorRepository()
        conv_a, conv_b = "conv-A", "conv-B"

        # A global corpus doc (Settings -> Documents), plus a large attachment ingested into A.
        await ingest_text(
            text="The global handbook covers vacation policy and remote work.",
            name="handbook.txt",
            document_id="global-doc",
            embed_model=EMBED_MODEL,
            provider=FakeModelProvider(),
            vectors=vectors,
            scope=GLOBAL_SCOPE,
        )
        await ingest_text(
            text="Wexford is the teal octopus mascot described in the attached report. " * 5,
            name="report.pdf",
            document_id="attach-doc",
            embed_model=EMBED_MODEL,
            provider=FakeModelProvider(),
            vectors=vectors,
            scope=Scope(conversation_id=conv_a),
        )

        # Union for A: both the attachment AND the global corpus are searchable.
        a_hits = _ids(await _retriever(vectors, union_conversation_id=conv_a).ainvoke("Wexford"))
        assert "attach-doc" in a_hits, "the attached doc must be retrievable in its conversation"
        a_global = _ids(await _retriever(vectors, union_conversation_id=conv_a).ainvoke("handbook"))
        assert "global-doc" in a_global, "the global corpus must stay searchable alongside"

        # ANTI-BLEED: conversation B's union must NOT see A's attachment.
        b_hits = _ids(await _retriever(vectors, union_conversation_id=conv_b).ainvoke("Wexford"))
        assert "attach-doc" not in b_hits, "ANTI-BLEED: another conversation must not see A's doc"

        # ANTI-BLEED: a no-conversation (global) request must NOT see A's attachment either.
        global_hits = _ids(await _retriever(vectors, union_conversation_id=None).ainvoke("Wexford"))
        assert "attach-doc" not in global_hits, "ANTI-BLEED: a global request must not see A's doc"

    asyncio.run(_run())


def test_idempotent_reingest_creates_no_duplicate_vectors() -> None:
    """Re-sending the SAME doc in the SAME conversation derives the SAME content-hash id, so the
    ingest-at-send path (which skips when the id already exists) adds no duplicate vectors. Here we
    also assert the lower-level upsert is idempotent by id even without the skip."""

    async def _run() -> None:
        vectors = InMemoryVectorRepository()
        conv = "conv-X"
        text = "Quarterly numbers and the revenue breakdown by region. " * 4
        doc_id = _conversation_document_id(conv, text)

        first = await ingest_text(
            text=text,
            name="q3.txt",
            document_id=doc_id,
            embed_model=EMBED_MODEL,
            provider=FakeModelProvider(),
            vectors=vectors,
            scope=Scope(conversation_id=conv),
        )
        after_first = len(await vectors.query([0.0] * 8, top_k=10_000, union_conversation_id=conv))

        # Re-ingest the identical content -> same vector ids -> upsert overwrites in place.
        second = await ingest_text(
            text=text,
            name="q3.txt",
            document_id=doc_id,
            embed_model=EMBED_MODEL,
            provider=FakeModelProvider(),
            vectors=vectors,
            scope=Scope(conversation_id=conv),
        )
        after_second = len(await vectors.query([0.0] * 8, top_k=10_000, union_conversation_id=conv))

        assert first.chunk_count == second.chunk_count
        assert after_first == after_second, "re-ingest must not accumulate duplicate vectors"

    asyncio.run(_run())


def test_conversation_document_id_is_stable_and_conversation_scoped() -> None:
    text = "same bytes"
    # Stable for the same (conversation, text).
    assert _conversation_document_id("c1", text) == _conversation_document_id("c1", text)
    # Different per conversation (so the same file in two chats gets two separate indexes).
    assert _conversation_document_id("c1", text) != _conversation_document_id("c2", text)
    # Different per content.
    assert _conversation_document_id("c1", "a") != _conversation_document_id("c1", "b")


def test_ingest_docs_from_turn_validates_and_caps() -> None:
    # Non-list -> empty.
    assert _ingest_docs_from_turn(None) == []
    assert _ingest_docs_from_turn("nope") == []
    # Allowlist: only name + text survive; nameless / empty-text items dropped.
    items = _ingest_docs_from_turn(
        [
            {"name": "a.txt", "text": "hello", "evil": "ignored"},
            {"name": "", "text": "no name"},
            {"name": "b.txt", "text": "   "},
            {"name": "c.txt", "text": "world"},
        ]
    )
    assert items == [("a.txt", "hello"), ("c.txt", "world")]
    # Per-item text cap (~128KB).
    big = _ingest_docs_from_turn([{"name": "big.txt", "text": "x" * (_INGEST_TEXT_CAP + 100)}])
    assert len(big[0][1]) == _INGEST_TEXT_CAP
    # Count cap.
    many = _ingest_docs_from_turn(
        [{"name": f"f{i}.txt", "text": "t"} for i in range(_MAX_INGEST_DOCS_PER_TURN + 5)]
    )
    assert len(many) == _MAX_INGEST_DOCS_PER_TURN
