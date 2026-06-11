"""Relational store for ingested documents (ADR-0005)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import asyncpg

from personalai_storage_postgres.db import TENANT_ID_SQL, Querier


@dataclass(frozen=True)
class Document:
    """Metadata about an ingested file."""

    id: str
    name: str
    mime: str
    size_bytes: int
    chunk_count: int
    created_at: datetime


class PgDocumentStore:
    """CRUD for the ``documents`` table."""

    def __init__(self, pool: Querier) -> None:
        self._pool = pool

    async def add(
        self, *, id: str, name: str, mime: str, size_bytes: int, chunk_count: int
    ) -> Document:
        row = await self._pool.fetchrow(
            f"INSERT INTO documents (id, name, mime, size_bytes, chunk_count, tenant_id) "
            f"VALUES ($1, $2, $3, $4, $5, {TENANT_ID_SQL}) "
            f"RETURNING id, name, mime, size_bytes, chunk_count, created_at",
            id,
            name,
            mime,
            size_bytes,
            chunk_count,
        )
        assert row is not None
        return _to_document(row)

    async def list(self) -> list[Document]:
        rows = await self._pool.fetch(
            "SELECT id, name, mime, size_bytes, chunk_count, created_at "
            "FROM documents ORDER BY created_at DESC"
        )
        return [_to_document(r) for r in rows]

    async def get(self, document_id: str) -> Document | None:
        row = await self._pool.fetchrow(
            "SELECT id, name, mime, size_bytes, chunk_count, created_at "
            "FROM documents WHERE id = $1",
            document_id,
        )
        return _to_document(row) if row is not None else None

    async def delete(self, document_id: str) -> None:
        await self._pool.execute("DELETE FROM documents WHERE id = $1", document_id)


def _to_document(row: asyncpg.Record) -> Document:
    return Document(
        id=row["id"],
        name=row["name"],
        mime=row["mime"],
        size_bytes=row["size_bytes"],
        chunk_count=row["chunk_count"],
        created_at=row["created_at"],
    )
