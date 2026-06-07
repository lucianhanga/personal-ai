"""File ingestion orchestration (M3-2): parse -> chunk -> embed -> store vectors.

Depends only on the contracts ports (ModelProvider, VectorRepository) and the file parsers, so it
is testable with fakes (no DB or live model needed). The relational document record and the
Postgres pool are handled by the endpoint/lifespan.
"""

from __future__ import annotations

from dataclasses import dataclass

from personalai_contracts.ports import ModelProvider, VectorRecord, VectorRepository
from personalai_modality_files import chunk_text, parse_document


@dataclass(frozen=True)
class IngestResult:
    """Summary of an ingested file."""

    document_id: str
    name: str
    mime: str
    size_bytes: int
    chunk_count: int


async def ingest_file(
    *,
    content: bytes,
    filename: str,
    document_id: str,
    embed_model: str,
    provider: ModelProvider,
    vectors: VectorRepository,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
) -> IngestResult:
    """Parse a file, chunk it, embed the chunks, and upsert them into the vector store."""
    parsed = parse_document(content, filename)
    chunks = chunk_text(parsed.text, size=chunk_size, overlap=chunk_overlap)
    if chunks:
        embeddings = await provider.embed(chunks, embed_model)
        records = [
            VectorRecord(
                id=f"{document_id}:{index}",
                vector=vector,
                metadata={
                    "document_id": document_id,
                    "name": filename,
                    "chunk_index": index,
                    "text": chunks[index],
                },
            )
            for index, vector in enumerate(embeddings.vectors)
        ]
        await vectors.upsert(records)
    return IngestResult(
        document_id=document_id,
        name=filename,
        mime=parsed.mime,
        size_bytes=len(content),
        chunk_count=len(chunks),
    )


def chunk_ids(document_id: str, chunk_count: int) -> list[str]:
    """Deterministic vector ids for a document's chunks (used to delete a document's vectors)."""
    return [f"{document_id}:{index}" for index in range(chunk_count)]
