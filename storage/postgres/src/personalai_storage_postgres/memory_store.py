"""pgvector-backed long-term memory store (M4-2), implementing the MemoryStore port."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import asyncpg

from personalai_contracts.ports import MemoryItem, MemoryKind
from personalai_storage_postgres.db import TENANT_ID_SQL, Querier
from personalai_storage_postgres.vector_repo import _to_pgvector

_COLS = "id, kind, text, confidence, source, superseded, created_at, updated_at"


class PgMemoryStore:
    """A :class:`MemoryStore` over Postgres + pgvector (cosine similarity)."""

    def __init__(self, pool: Querier) -> None:
        self._pool = pool

    async def add(
        self,
        *,
        id: str,
        kind: MemoryKind,
        text: str,
        embedding: Sequence[float],
        confidence: float,
        source: Mapping[str, str],
    ) -> MemoryItem:
        row = await self._pool.fetchrow(
            f"INSERT INTO memories (id, kind, text, embedding, confidence, source, tenant_id) "
            f"VALUES ($1, $2, $3, $4::vector, $5, $6::jsonb, {TENANT_ID_SQL}) "
            f"RETURNING {_COLS}",
            id,
            kind.value,
            text,
            _to_pgvector(embedding),
            confidence,
            json.dumps(dict(source)),
        )
        assert row is not None
        return _to_memory(row)

    async def search(self, embedding: Sequence[float], top_k: int = 5) -> Sequence[MemoryItem]:
        rows = await self._pool.fetch(
            f"SELECT {_COLS}, 1 - (embedding <=> $1::vector) AS score "
            "FROM memories WHERE NOT superseded ORDER BY embedding <=> $1::vector LIMIT $2",
            _to_pgvector(embedding),
            top_k,
        )
        return [_to_memory(r, score=float(r["score"])) for r in rows]

    async def list(self) -> Sequence[MemoryItem]:
        rows = await self._pool.fetch(
            f"SELECT {_COLS} FROM memories WHERE NOT superseded ORDER BY created_at DESC"
        )
        return [_to_memory(r) for r in rows]

    async def get(self, memory_id: str) -> MemoryItem | None:
        row = await self._pool.fetchrow(f"SELECT {_COLS} FROM memories WHERE id = $1", memory_id)
        return _to_memory(row) if row is not None else None

    async def update_text(self, memory_id: str, text: str) -> MemoryItem | None:
        row = await self._pool.fetchrow(
            f"UPDATE memories SET text = $2, updated_at = now() WHERE id = $1 RETURNING {_COLS}",
            memory_id,
            text,
        )
        return _to_memory(row) if row is not None else None

    async def supersede(self, memory_id: str) -> MemoryItem | None:
        row = await self._pool.fetchrow(
            f"UPDATE memories SET superseded = true, updated_at = now() WHERE id = $1 "
            f"RETURNING {_COLS}",
            memory_id,
        )
        return _to_memory(row) if row is not None else None

    async def delete(self, memory_id: str) -> None:
        await self._pool.execute("DELETE FROM memories WHERE id = $1", memory_id)

    async def clear(self) -> None:
        await self._pool.execute("DELETE FROM memories")


def _to_memory(row: asyncpg.Record, *, score: float | None = None) -> MemoryItem:
    return MemoryItem(
        id=row["id"],
        kind=MemoryKind(row["kind"]),
        text=row["text"],
        confidence=row["confidence"],
        source=json.loads(row["source"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        superseded=row["superseded"],
        score=score,
    )
