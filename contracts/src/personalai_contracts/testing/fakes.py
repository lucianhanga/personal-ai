"""In-memory reference implementations of every port.

These are deterministic test doubles used to prove the ports are implementable and to back
unit tests across packages (e.g. agent/orchestration tests can use ``FakeModelProvider``).
They are NOT production adapters. They depend only on the ports (ADR-0001).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from personalai_contracts.ports.agent import AgentContext, AgentNode, AgentState
from personalai_contracts.ports.modality import (
    MediaRef,
    ModalityKind,
    ParsedContent,
)
from personalai_contracts.ports.model_provider import (
    EmbeddingResult,
    GenerationRequest,
    GenerationResult,
    ModelCapabilities,
)
from personalai_contracts.ports.retriever import RetrievalQuery, RetrievedItem
from personalai_contracts.ports.storage import (
    VectorMatch,
    VectorRecord,
)
from personalai_contracts.ports.tool import ToolCall, ToolResult

_EMBED_DIM = 8


def _deterministic_vector(text: str) -> list[float]:
    """A stable, content-derived vector for testing (fixed dimensionality)."""
    vec = [0.0] * _EMBED_DIM
    for i, ch in enumerate(text):
        vec[i % _EMBED_DIM] += float(ord(ch) % 17)
    return vec


class FakeModelProvider:
    """A model provider that echoes the last user message and embeds deterministically."""

    def __init__(self, name: str = "fake", capabilities: ModelCapabilities | None = None) -> None:
        self.name = name
        self._capabilities = capabilities or ModelCapabilities(
            text=True, embeddings=True, tool_calling=True, structured_output=True
        )

    def capabilities(self, model: str) -> ModelCapabilities:
        return self._capabilities

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        last = request.messages[-1].content if request.messages else ""
        return GenerationResult(text=f"echo: {last}", model=request.model, finish_reason="stop")

    async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
        vectors = [_deterministic_vector(t) for t in texts]
        return EmbeddingResult(vectors=vectors, model=model, dimensions=_EMBED_DIM)


class FakeRetriever:
    """A retriever that returns preloaded items, truncated to ``top_k``."""

    def __init__(self, items: Sequence[RetrievedItem], name: str = "fake") -> None:
        self.name = name
        self._items = list(items)

    async def retrieve(self, query: RetrievalQuery) -> Sequence[RetrievedItem]:
        ranked = sorted(self._items, key=lambda i: i.score, reverse=True)
        return ranked[: query.top_k]


class InMemoryRepository[T]:
    """A dict-backed generic repository keyed by a caller-supplied id getter."""

    def __init__(self, id_getter: Callable[[T], str]) -> None:
        self._id_getter = id_getter
        self._store: dict[str, T] = {}

    async def add(self, entity: T) -> None:
        self._store[self._id_getter(entity)] = entity

    async def get(self, entity_id: str) -> T | None:
        return self._store.get(entity_id)

    async def list(self) -> Sequence[T]:
        return list(self._store.values())

    async def delete(self, entity_id: str) -> None:
        self._store.pop(entity_id, None)


class InMemoryVectorRepository:
    """A vector store ranking by dot-product similarity."""

    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}

    async def upsert(self, records: Sequence[VectorRecord]) -> None:
        for record in records:
            self._records[record.id] = record

    async def query(self, vector: Sequence[float], top_k: int = 5) -> Sequence[VectorMatch]:
        scored = [
            VectorMatch(
                id=rec.id,
                score=sum(a * b for a, b in zip(vector, rec.vector, strict=False)),
                metadata=rec.metadata,
            )
            for rec in self._records.values()
        ]
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:top_k]

    async def delete(self, ids: Sequence[str]) -> None:
        for vid in ids:
            self._records.pop(vid, None)


class InMemoryObjectStore:
    """A dict-backed object store."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        self._blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self._blobs[key]

    async def exists(self, key: str) -> bool:
        return key in self._blobs

    async def delete(self, key: str) -> None:
        self._blobs.pop(key, None)


class InMemoryGraphStore:
    """A minimal adjacency-list graph store (KAG stub)."""

    def __init__(self) -> None:
        self._edges: dict[str, list[str]] = {}

    async def add_edge(self, src: str, relation: str, dst: str) -> None:
        self._edges.setdefault(src, []).append(dst)

    async def neighbors(self, node: str) -> Sequence[str]:
        return list(self._edges.get(node, []))


class EchoModalityHandler:
    """A text modality handler that returns the URI as parsed content."""

    def __init__(self, kind: ModalityKind = ModalityKind.TEXT) -> None:
        self.kind = kind

    def can_handle(self, mime_type: str) -> bool:
        return mime_type.startswith("text/")

    async def parse(self, ref: MediaRef) -> ParsedContent:
        return ParsedContent(text=ref.uri, metadata={"kind": ref.kind.value})


class EchoAgentNode:
    """An agent node that records that it ran into the state."""

    def __init__(self, name: str = "echo") -> None:
        self.name = name

    async def run(self, state: AgentState, context: AgentContext) -> AgentState:
        return {**state, "ran": self.name, "conversation_id": context.conversation_id}


class EchoAgentRole:
    """An agent role exposing an :class:`EchoAgentNode`."""

    def __init__(self, name: str = "echo", description: str = "Echo role for tests") -> None:
        self.name = name
        self.description = description

    def node(self) -> AgentNode:
        return EchoAgentNode(self.name)


class EchoToolHandler:
    """A tool handler that echoes its args back as output."""

    def __init__(self, name: str = "echo") -> None:
        self.name = name

    async def invoke(self, call: ToolCall) -> ToolResult:
        return ToolResult(ok=True, output={"tool": call.tool, "args": dict(call.args)})
