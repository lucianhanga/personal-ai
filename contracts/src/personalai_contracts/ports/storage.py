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
    """Vector upsert / similarity-search / delete."""

    async def upsert(self, records: Sequence[VectorRecord]) -> None: ...

    async def query(self, vector: Sequence[float], top_k: int = 5) -> Sequence[VectorMatch]: ...

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
