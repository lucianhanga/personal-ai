"""pgvector-backed VectorRepository (ADR-0005).

Implements the ``VectorRepository`` port over a Postgres ``vectors`` table using cosine distance.
Depends inward on ``personalai_contracts`` only (ADR-0001).
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import asyncpg

from personalai_contracts.ports.storage import VectorMatch, VectorRecord

# Embedding dimension of the default embedding model (mxbai-embed-large).
VECTOR_DIM = 1024


def _to_pgvector(values: Sequence[float]) -> str:
    """Render a float sequence as a pgvector literal, e.g. ``[0.1,0.2]``."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


class PgVectorRepository:
    """A :class:`VectorRepository` backed by Postgres + pgvector (cosine similarity)."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert(self, records: Sequence[VectorRecord]) -> None:
        await self._pool.executemany(
            "INSERT INTO vectors (id, embedding, metadata) VALUES ($1, $2::vector, $3::jsonb) "
            "ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding, "
            "metadata = EXCLUDED.metadata",
            [(r.id, _to_pgvector(r.vector), json.dumps(dict(r.metadata))) for r in records],
        )

    async def query(self, vector: Sequence[float], top_k: int = 5) -> Sequence[VectorMatch]:
        rows = await self._pool.fetch(
            "SELECT id, metadata, 1 - (embedding <=> $1::vector) AS score "
            "FROM vectors ORDER BY embedding <=> $1::vector LIMIT $2",
            _to_pgvector(vector),
            top_k,
        )
        return [
            VectorMatch(
                id=row["id"], score=float(row["score"]), metadata=json.loads(row["metadata"])
            )
            for row in rows
        ]

    async def delete(self, ids: Sequence[str]) -> None:
        await self._pool.execute("DELETE FROM vectors WHERE id = ANY($1::text[])", list(ids))
