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

# Reciprocal Rank Fusion constant (#420 hybrid retrieval). 60 is the canonical RRF k from the
# original paper and the doktokNG HybridPostgresRetriever -- it damps the contribution of low ranks
# so a single arm's tail can't dominate the fused order.
_RRF_K = 60


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

    async def hybrid_query(
        self,
        vector: Sequence[float],
        text: str,
        top_k: int = 5,
        *,
        scope: Scope = GLOBAL_SCOPE,
    ) -> Sequence[VectorMatch]:
        # ONE query, two arms fused by Reciprocal Rank Fusion (RRF, k=60 canonical), the doktokNG
        # HybridPostgresRetriever shape (#420 storage design): a dense arm (pgvector cosine over the
        # HNSW index) and a lexical arm (ts_rank_cd over the `simple`-config `tsv` GIN, migration
        # 0023) each take their own top-k, then we fuse by rank -- score = sum(1/(60 + rank)). RRF
        # is rank-based (no score normalization) so the cosine and FTS halves combine cleanly, and
        # a lexical-exact hit the dense arm alone would rank lower can surface.
        #
        # $1=qvec, $2=qtext, $3=k (per-arm + final LIMIT), $4=rrf constant. The scope predicate's
        # bound params start at $5 and are reused verbatim in BOTH arms (the same scope filters
        # dense and lexical identically -- anti-bleed). Tenant is enforced by RLS on the
        # tenant-bound connection and is intentionally absent from this SQL. `_init_connection` sets
        # `hnsw.iterative_scan = relaxed_order`, so a scoped (filtered) dense arm still returns a
        # full k. The scope value is bound, never interpolated.
        predicate, scope_params = scope_predicate(scope, next_param=5)
        rows = await self._pool.fetch(
            "WITH dense AS ("
            "  SELECT id, metadata, "
            "         row_number() OVER (ORDER BY embedding <=> $1::vector) AS rnk "
            "  FROM vectors "
            f"  WHERE {predicate} "
            "  ORDER BY embedding <=> $1::vector "
            "  LIMIT $3"
            "), "
            "lexical AS ("
            "  SELECT id, metadata, "
            "         row_number() OVER ("
            "             ORDER BY ts_rank_cd(tsv, plainto_tsquery('simple', $2)) DESC"
            "         ) AS rnk "
            "  FROM vectors "
            f"  WHERE {predicate} "
            "    AND tsv @@ plainto_tsquery('simple', $2) "
            "  ORDER BY ts_rank_cd(tsv, plainto_tsquery('simple', $2)) DESC "
            "  LIMIT $3"
            ") "
            "SELECT id, metadata, sum(1.0 / ($4 + rnk)) AS score "
            "FROM (SELECT id, metadata, rnk FROM dense "
            "      UNION ALL "
            "      SELECT id, metadata, rnk FROM lexical) fused "
            "GROUP BY id, metadata "
            "ORDER BY score DESC "
            "LIMIT $3",
            _to_pgvector(vector),
            text,
            top_k,
            _RRF_K,
            *scope_params,
        )
        return [
            VectorMatch(
                id=row["id"], score=float(row["score"]), metadata=json.loads(row["metadata"])
            )
            for row in rows
        ]

    async def delete(self, ids: Sequence[str]) -> None:
        await self._pool.execute("DELETE FROM vectors WHERE id = ANY($1::text[])", list(ids))
