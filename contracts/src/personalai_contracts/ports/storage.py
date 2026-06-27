"""Ports: storage repositories.

Repository interfaces for the storage spine (ADR-0005): a generic relational repository,
a vector repository, an object store, and a graph-store stub (KAG, M10). Concrete adapters
(postgres, pgvector, qdrant, object-store, neo4j/age) live under ``storage/`` and are
selected via dependency injection (M0-4).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Repository[T](Protocol):
    """A generic, async, id-addressable repository for entities of type ``T``."""

    async def add(self, entity: T) -> None: ...

    async def get(self, entity_id: str) -> T | None: ...

    async def list(self) -> Sequence[T]: ...

    async def delete(self, entity_id: str) -> None: ...


@dataclass(frozen=True)
class Scope:
    """The corpus partition a vector/document belongs to (the generic RAG scope dimension, #420).

    Exactly one of ``conversation_id`` / ``project_id`` may be set; both ``None`` is the **global**
    (tenant / Settings -> Documents) corpus. Mirrors the nullable ``conversation_id``/``project_id``
    columns on ``vectors`` and ``documents`` (migration 0023). Scope is an *additional* app-layer
    filter on top of tenant RLS, never a replacement for it.
    """

    conversation_id: str | None = None
    project_id: str | None = None

    def __post_init__(self) -> None:
        if self.conversation_id is not None and self.project_id is not None:
            raise ValueError(
                "Scope is mutually exclusive: set conversation_id or project_id, not both"
            )

    @property
    def is_global(self) -> bool:
        """True for the global corpus (no conversation/project scope)."""
        return self.conversation_id is None and self.project_id is None


# The default scope for unscoped callers: today's global corpus (conversation_id/project_id NULL).
GLOBAL_SCOPE = Scope()


@dataclass(frozen=True)
class VectorRecord:
    """A stored embedding with its metadata."""

    id: str
    vector: Sequence[float]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorMatch:
    """A nearest-neighbour search hit."""

    id: str
    score: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class VectorRepository(Protocol):
    """Vector upsert / similarity-search / delete.

    ``scope`` defaults to :data:`GLOBAL_SCOPE` so existing callers keep reading/writing the global
    corpus unchanged. A global ``query`` MUST exclude conversation/project rows (anti-bleed, #420).
    """

    async def upsert(
        self, records: Sequence[VectorRecord], *, scope: Scope = GLOBAL_SCOPE
    ) -> None: ...

    async def query(
        self,
        vector: Sequence[float],
        top_k: int = 5,
        *,
        scope: Scope = GLOBAL_SCOPE,
        union_conversation_id: str | None = None,
    ) -> Sequence[VectorMatch]: ...

    async def hybrid_query(
        self,
        vector: Sequence[float],
        text: str,
        top_k: int = 5,
        *,
        scope: Scope = GLOBAL_SCOPE,
        union_conversation_id: str | None = None,
    ) -> Sequence[VectorMatch]:
        """Dense (pgvector cosine) + lexical (FTS) retrieval fused by Reciprocal Rank Fusion (#420).

        Runs ONE query: a dense arm over the embedding index and a lexical arm over the chunk-text
        full-text column, each top-N, fused by RRF (k=60). ``score`` on the returned matches is the
        RRF score (rank-based, not cosine), so citations are preserved while ranking improves. Same
        ``scope`` / anti-bleed semantics as :meth:`query`; the global default excludes
        conversation/project rows.

        ``union_conversation_id`` (#420 PR4): when set, retrieval covers the UNION of the global
        corpus AND that conversation's ephemeral attachments (``global OR conversation_id = :cid``),
        so an attached large doc and the global corpus are both searchable in one question. It takes
        precedence over ``scope`` and preserves anti-bleed: only rows whose ``conversation_id``
        equals the bound id (plus global rows) can match -- another conversation's rows never do.
        """
        ...

    async def chunks_for_document(self, document_id: str) -> Sequence[tuple[int, str]]:
        """Return ``(chunk_index, text)`` for a document's chunks, ordered by index -- for the
        Knowledge chunk inspector (#465)."""
        ...

    async def delete(self, ids: Sequence[str]) -> None: ...


@runtime_checkable
class ObjectStore(Protocol):
    """Encrypted-at-rest blob storage for files/artifacts."""

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def exists(self, key: str) -> bool: ...

    async def delete(self, key: str) -> None: ...


@runtime_checkable
class GraphStore(Protocol):
    """Graph/KAG store stub (optional, M11). Minimal edge + neighbour interface."""

    async def add_edge(self, src: str, relation: str, dst: str) -> None: ...

    async def neighbors(self, node: str) -> Sequence[str]: ...


class MemoryKind(StrEnum):
    """Category of a long-term memory (M4)."""

    SEMANTIC = "semantic"  # durable facts ("X works at Y")
    EPISODIC = "episodic"  # events ("on <date> you asked ...")
    PREFERENCE = "preference"  # how the user likes things ("answer concisely")


@dataclass(frozen=True)
class MemoryItem:
    """A stored long-term memory with provenance (read shape)."""

    id: str
    kind: MemoryKind
    text: str
    confidence: float
    source: Mapping[str, str]
    created_at: datetime
    updated_at: datetime
    superseded: bool = False
    score: float | None = None  # similarity score when returned from search()


@runtime_checkable
class MemoryStore(Protocol):
    """Long-term semantic memory: store, vector-search, list, delete (M4)."""

    async def add(
        self,
        *,
        id: str,
        kind: MemoryKind,
        text: str,
        embedding: Sequence[float],
        confidence: float,
        source: Mapping[str, str],
    ) -> MemoryItem: ...

    async def search(self, embedding: Sequence[float], top_k: int = 5) -> Sequence[MemoryItem]: ...

    async def list(self) -> Sequence[MemoryItem]: ...

    async def get(self, memory_id: str) -> MemoryItem | None: ...

    async def update_text(self, memory_id: str, text: str) -> MemoryItem | None: ...

    async def supersede(self, memory_id: str) -> MemoryItem | None: ...

    """Mark a memory superseded (hidden from search/list) when a newer fact replaces it."""

    async def delete(self, memory_id: str) -> None: ...

    async def clear(self) -> None: ...
