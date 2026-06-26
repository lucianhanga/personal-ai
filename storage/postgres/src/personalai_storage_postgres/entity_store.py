"""KAG entity store (#451): canonical named entities + document mentions + the entity graph.

Mirrors the other Pg stores (a thin layer over a tenant-bound ``Querier``; all SQL is RLS-scoped by
``app.tenant_id``). Entities derive only from the durable GLOBAL corpus, so there are no scope
columns -- tenant is the only isolation dimension. The canonical upsert folds re-extractions of the
same ``(type, normalized_name)`` across documents into one row; ``document_id`` is a soft link to
``documents`` (reconciler-purged, like vectors), so purging a document drops its mentions and
decrements the counters, and the orphan sweep removes entities that no document references.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import asyncpg

from personalai_storage_postgres.db import Querier


@dataclass(frozen=True)
class Entity:
    """A canonical named entity for the knowledge graph."""

    id: str
    type: str
    name: str
    normalized_name: str
    mention_count: int


class PgEntityStore:
    """CRUD + reconciler for ``entities`` / ``entity_documents`` / ``entity_edges``."""

    def __init__(self, pool: Querier) -> None:
        self._pool = pool

    async def upsert_entity(self, *, type: str, name: str, occurrences: int = 1) -> str:
        """Insert or fold an entity by its canonical ``(type, normalized_name)`` key; returns id.
        On conflict the mention counter accumulates and the display ``name`` takes the latest."""
        row = await self._pool.fetchrow(
            "INSERT INTO entities (tenant_id, type, name, mention_count) "
            "VALUES (current_setting('app.tenant_id')::uuid, $1, $2, $3) "
            "ON CONFLICT (tenant_id, type, normalized_name) DO UPDATE SET "
            "mention_count = entities.mention_count + excluded.mention_count, "
            "name = excluded.name, updated_at = now() "
            "RETURNING id",
            type,
            name,
            occurrences,
        )
        assert row is not None
        return str(row["id"])

    async def add_mention(self, *, entity_id: str, document_id: str, occurrences: int = 1) -> None:
        """Link an entity to a document (the M:N mention)."""
        await self._pool.execute(
            "INSERT INTO entity_documents (tenant_id, entity_id, document_id, occurrences) "
            "VALUES (current_setting('app.tenant_id')::uuid, $1, $2, $3) "
            "ON CONFLICT (tenant_id, entity_id, document_id) DO UPDATE SET "
            "occurrences = excluded.occurrences",
            entity_id,
            document_id,
            occurrences,
        )

    async def add_edge(self, *, src_entity_id: str, relation: str, dst_entity_id: str) -> None:
        """Add or reinforce a directed graph edge (no-op on a self-loop)."""
        if src_entity_id == dst_entity_id:
            return
        await self._pool.execute(
            "INSERT INTO entity_edges (tenant_id, src_entity_id, relation, dst_entity_id) "
            "VALUES (current_setting('app.tenant_id')::uuid, $1, $2, $3) "
            "ON CONFLICT (tenant_id, src_entity_id, relation, dst_entity_id) DO UPDATE SET "
            "weight = entity_edges.weight + 1, updated_at = now()",
            src_entity_id,
            relation,
            dst_entity_id,
        )

    async def purge_document_entities(self, document_id: str) -> None:
        """Reconciler (a): drop a document's mentions and decrement the entities' counters. Run this
        BEFORE re-extracting a document (idempotency) and when a document is purged."""
        await self._pool.execute(
            "WITH removed AS ("
            "  DELETE FROM entity_documents "
            "  WHERE tenant_id = current_setting('app.tenant_id')::uuid AND document_id = $1 "
            "  RETURNING entity_id, occurrences"
            ") "
            "UPDATE entities e "
            "SET mention_count = GREATEST(e.mention_count - r.total, 0), updated_at = now() "
            "FROM (SELECT entity_id, sum(occurrences) AS total FROM removed GROUP BY entity_id) r "
            "WHERE e.tenant_id = current_setting('app.tenant_id')::uuid AND e.id = r.entity_id",
            document_id,
        )

    async def sweep_orphan_entities(self, *, grace_hours: int = 1) -> int:
        """Reconciler (b): delete entities no document references (past the grace window); their
        edges cascade. Returns the number removed. The grace window protects an in-flight extraction
        (entity minted, mention not yet inserted)."""
        result = await self._pool.execute(
            "DELETE FROM entities e "
            "WHERE e.tenant_id = current_setting('app.tenant_id')::uuid "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM entity_documents ed "
            "  WHERE ed.tenant_id = e.tenant_id AND ed.entity_id = e.id"
            ") "
            "AND e.updated_at < now() - make_interval(hours => $1)",
            grace_hours,
        )
        return _rowcount(result)

    async def list_entities(
        self, *, type: str | None = None, query: str | None = None, limit: int = 50
    ) -> list[Entity]:
        """List entities, optionally filtered by ``type`` and/or a fuzzy ``query`` over the
        canonical name (trigram-indexed ILIKE), most-mentioned first."""
        clauses = ["tenant_id = current_setting('app.tenant_id')::uuid"]
        params: list[Any] = []
        if type is not None:
            params.append(type)
            clauses.append(f"type = ${len(params)}")
        if query:
            params.append(query.lower())
            clauses.append(f"normalized_name ILIKE '%' || ${len(params)} || '%'")
        params.append(min(max(limit, 1), 200))
        rows = await self._pool.fetch(
            f"SELECT id, type, name, normalized_name, mention_count FROM entities "
            f"WHERE {' AND '.join(clauses)} "
            f"ORDER BY mention_count DESC, name ASC LIMIT ${len(params)}",
            *params,
        )
        return [_to_entity(r) for r in rows]

    async def get_entity(self, entity_id: str) -> Entity | None:
        row = await self._pool.fetchrow(
            "SELECT id, type, name, normalized_name, mention_count FROM entities WHERE id = $1",
            entity_id,
        )
        return _to_entity(row) if row is not None else None

    async def documents_for_entity(self, entity_id: str) -> list[str]:
        rows = await self._pool.fetch(
            "SELECT document_id FROM entity_documents WHERE entity_id = $1 ORDER BY document_id",
            entity_id,
        )
        return [str(r["document_id"]) for r in rows]

    async def entities_for_document(self, document_id: str) -> list[Entity]:
        rows = await self._pool.fetch(
            "SELECT e.id, e.type, e.name, e.normalized_name, e.mention_count "
            "FROM entities e JOIN entity_documents ed ON ed.entity_id = e.id "
            "WHERE ed.document_id = $1 ORDER BY e.mention_count DESC, e.name ASC",
            document_id,
        )
        return [_to_entity(r) for r in rows]

    async def edges_for_entity(self, entity_id: str) -> list[tuple[str, str]]:
        """Outgoing edges from ``entity_id`` as ``(relation, dst_entity_id)``."""
        rows = await self._pool.fetch(
            "SELECT relation, dst_entity_id FROM entity_edges WHERE src_entity_id = $1 "
            "ORDER BY weight DESC, relation",
            entity_id,
        )
        return [(str(r["relation"]), str(r["dst_entity_id"])) for r in rows]


def _rowcount(result: Any) -> int:
    # asyncpg execute() returns a status string like "DELETE 3"; the trailing int is the row count.
    try:
        return int(str(result).rsplit(" ", 1)[1])
    except (IndexError, ValueError):
        return 0


def _to_entity(row: asyncpg.Record) -> Entity:
    return Entity(
        id=str(row["id"]),
        type=row["type"],
        name=row["name"],
        normalized_name=row["normalized_name"],
        mention_count=row["mention_count"],
    )
