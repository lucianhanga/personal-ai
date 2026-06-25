"""pgvector-backed VectorRepository (ADR-0005).

Implements the ``VectorRepository`` port over a Postgres ``vectors`` table using cosine distance.
Depends inward on ``personalai_contracts`` only (ADR-0001).
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from personalai_contracts.ports.storage import GLOBAL_SCOPE, Scope, VectorMatch, VectorRecord
from personalai_storage_postgres.db import TENANT_ID_SQL, Querier, scope_predicate

# Embedding dimension of the default embedding model (qwen3-embedding:0.6b).
VECTOR_DIM = 1024


def _to_pgvector(values: Sequence[float]) -> str:
    """Render a float sequence as a pgvector literal, e.g. ``[0.1,0.2]``."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


class PgVectorRepository:
    """A :class:`VectorRepository` backed by Postgres + pgvector (cosine similarity)."""

    def __init__(self, pool: Querier) -> None:
        self._pool = pool

    async def upsert(self, records: Sequence[VectorRecord], *, scope: Scope = GLOBAL_SCOPE) -> None:
        # Scope columns are bound params (4, 5), never interpolated. NULL/NULL = global corpus.
        await self._pool.executemany(
            f"INSERT INTO vectors "
            f"(id, embedding, metadata, tenant_id, conversation_id, project_id) "
            f"VALUES ($1, $2::vector, $3::jsonb, {TENANT_ID_SQL}, $4, $5) "
            f"ON CONFLICT (tenant_id, id) DO UPDATE SET embedding = EXCLUDED.embedding, "
            f"metadata = EXCLUDED.metadata, conversation_id = EXCLUDED.conversation_id, "
            f"project_id = EXCLUDED.project_id",
            [
                (
                    r.id,
                    _to_pgvector(r.vector),
                    json.dumps(dict(r.metadata)),
                    scope.conversation_id,
                    scope.project_id,
                )
                for r in records
            ],
        )

    async def query(
        self, vector: Sequence[float], top_k: int = 5, *, scope: Scope = GLOBAL_SCOPE
    ) -> Sequence[VectorMatch]:
        # Scope is an additional app-layer filter on top of tenant RLS. The global default adds
        # `conversation_id IS NULL AND project_id IS NULL` so conversation/project rows can never
        # leak into a global search (anti-bleed, #420). Scoped predicates are fully parameterized.
        predicate, params = scope_predicate(scope, next_param=2)
        rows = await self._pool.fetch(
            "SELECT id, metadata, 1 - (embedding <=> $1::vector) AS score "
            f"FROM vectors WHERE {predicate} "
            f"ORDER BY embedding <=> $1::vector LIMIT ${len(params) + 2}",
            _to_pgvector(vector),
            *params,
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
