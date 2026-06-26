"""File ingestion orchestration (M3-2): parse -> chunk -> embed -> store vectors.

Depends only on the contracts ports (ModelProvider, VectorRepository) and the file parsers, so it
is testable with fakes (no DB or live model needed). The relational document record and the
Postgres pool are handled by the endpoint/lifespan.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from personalai_contracts.ports import ModelProvider, VectorRecord, VectorRepository
from personalai_contracts.ports.storage import GLOBAL_SCOPE, Scope
from personalai_modality_files import chunk_text, parse_document


@dataclass(frozen=True)
class IngestResult:
    """Summary of an ingested file."""

    document_id: str
    name: str
    mime: str
    size_bytes: int
    chunk_count: int


async def _chunk_embed_store(
    *,
    text: str,
    name: str,
    document_id: str,
    embed_model: str,
    provider: ModelProvider,
    vectors: VectorRepository,
    scope: Scope,
    chunk_size: int,
    chunk_overlap: int,
) -> int:
    """Shared pipeline tail: chunk pre-parsed ``text``, embed, and upsert into ``scope``.

    Returns the chunk count. ``scope`` flows straight through to ``vectors.upsert`` so the rows
    carry the right ``conversation_id``/``project_id`` (global by default). The chunk text is stored
    in the vector metadata (``text``) -- the lexical (FTS) source the hybrid retriever reads, and
    the ONLY place the full document text is persisted for a tier-2 attachment (never in the
    conversation turn's display meta).
    """
    chunks = chunk_text(text, size=chunk_size, overlap=chunk_overlap)
    if not chunks:
        return 0
    embeddings = await provider.embed(chunks, embed_model)
    records = [
        VectorRecord(
            id=f"{document_id}:{index}",
            vector=vector,
            metadata={
                "document_id": document_id,
                "name": name,
                "chunk_index": index,
                "text": chunks[index],
            },
        )
        for index, vector in enumerate(embeddings.vectors)
    ]
    await vectors.upsert(records, scope=scope)
    return len(chunks)


async def ingest_file(
    *,
    content: bytes,
    filename: str,
    document_id: str,
    embed_model: str,
    provider: ModelProvider,
    vectors: VectorRepository,
    scope: Scope = GLOBAL_SCOPE,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
) -> IngestResult:
    """Parse a file, chunk it, embed the chunks, and upsert them into the vector store.

    ``scope`` defaults to the global corpus so the Settings -> Documents path is unchanged (#420).
    """
    parsed = parse_document(content, filename)
    chunk_count = await _chunk_embed_store(
        text=parsed.text,
        name=filename,
        document_id=document_id,
        embed_model=embed_model,
        provider=provider,
        vectors=vectors,
        scope=scope,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return IngestResult(
        document_id=document_id,
        name=filename,
        mime=parsed.mime,
        size_bytes=len(content),
        chunk_count=chunk_count,
    )


async def ingest_text(
    *,
    text: str,
    name: str,
    document_id: str,
    embed_model: str,
    provider: ModelProvider,
    vectors: VectorRepository,
    scope: Scope = GLOBAL_SCOPE,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
) -> IngestResult:
    """Ingest ALREADY-PARSED text (no byte re-parse) -- the tier-2 ingest-at-send path (#420 PR4).

    The chat send flow already carries each large attachment's extracted text (the UI obtained it
    from ``/files/extract``), so re-parsing bytes server-side would be wasteful and lossy. Same
    chunk/embed/upsert pipeline as :func:`ingest_file`, but the caller supplies the text and the
    conversation ``scope`` directly. ``size_bytes`` is the UTF-8 length of the text (there is no
    original file on this path). ``mime`` is reported as ``text/plain`` -- the document record is
    bookkeeping for idempotency/GC, not a re-downloadable blob.
    """
    chunk_count = await _chunk_embed_store(
        text=text,
        name=name,
        document_id=document_id,
        embed_model=embed_model,
        provider=provider,
        vectors=vectors,
        scope=scope,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return IngestResult(
        document_id=document_id,
        name=name,
        mime="text/plain",
        size_bytes=len(text.encode("utf-8")),
        chunk_count=chunk_count,
    )


def chunk_ids(document_id: str, chunk_count: int) -> list[str]:
    """Deterministic vector ids for a document's chunks (used to delete a document's vectors)."""
    return [f"{document_id}:{index}" for index in range(chunk_count)]


def content_document_id(content: bytes) -> str:
    """Content-addressed global document id for a folder-synced file (#456).

    Same bytes -> same id, so the same file appearing in two watched folders dedups to ONE vector
    set (the chunk/embed step is idempotent on this id). Distinct from manual uploads' uuid ids, so
    a folder file and a manual upload of identical content stay separate records (and the manual one
    keeps ``manual_pin=true``)."""
    return "global-" + hashlib.sha256(content).hexdigest()
