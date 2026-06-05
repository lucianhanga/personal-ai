# Contracts & Ports Reference

The **ports** are the stable interfaces (seams) that adapters implement. They live in the
`personalai_contracts` package — the innermost layer of the hexagonal architecture
([ADR-0001](../architecture/adr/0001-modular-monolith-hexagonal.md)). This document describes
every port as it is **actually implemented today (M0-2)**: its responsibility, its `Protocol`
methods, its value objects, sync-vs-async surface, and a minimal adapter example.

> Status: M0-2 delivers the ports and the reference fakes. Versioned schemas, the agent message
> envelope, and the tool-invocation/manifest contracts arrive in **M0-3**. The registries and DI
> wiring that discover adapters arrive in **M0-4**. Items marked *planned (Mx)* do not exist yet.

## Source of truth

- Ports: `contracts/src/personalai_contracts/ports/*.py`
- Public re-exports: `contracts/src/personalai_contracts/ports/__init__.py`
- Reference fakes: `contracts/src/personalai_contracts/testing/fakes.py`
- Port behaviour tests: `contracts/tests/test_ports.py`

If this document disagrees with the code, the code wins — please open a fix.

## Conventions shared by all ports

- Each port is a `typing.Protocol` decorated with `@runtime_checkable`, so
  `isinstance(adapter, ModelProvider)` works structurally (the tests rely on this).
- Value objects are `@dataclass(frozen=True)` (immutable); enums are `enum.StrEnum`.
- I/O-bound methods are `async def`; cheap, CPU-only lookups (`capabilities`, `can_handle`) are
  plain `def`.
- Mappings use `collections.abc.Mapping`; sequences use `collections.abc.Sequence` (read-only,
  variance-friendly). `from __future__ import annotations` is on in every module.
- Adapters depend **inward on `personalai_contracts` only** and **never import each other**
  ([ADR-0001](../architecture/adr/0001-modular-monolith-hexagonal.md)); the core never imports a
  concrete adapter. This direction is enforced by import-linter — see
  [coding-standards.md](../development/coding-standards.md).

## Ports at a glance

| Port | Module | Sync methods | Async methods | Establishing milestone |
|---|---|---|---|---|
| `ModelProvider` | `ports/model_provider.py` | `capabilities` | `generate`, `embed` | M1 |
| `Retriever` | `ports/retriever.py` | — | `retrieve` | M3 |
| `Repository[T]` | `ports/storage.py` | — | `add`, `get`, `list`, `delete` | M3 |
| `VectorRepository` | `ports/storage.py` | — | `upsert`, `query`, `delete` | M3 |
| `ObjectStore` | `ports/storage.py` | — | `put`, `get`, `exists`, `delete` | M3 |
| `GraphStore` | `ports/storage.py` | — | `add_edge`, `neighbors` | M10 (stub now) |
| `ModalityHandler` | `ports/modality.py` | `can_handle` | `parse` | M3 / M8 |
| `AgentRole` / `AgentNode` | `ports/agent.py` | `node` | `run` | M6 |
| `ToolHandler` | `ports/tool.py` | — | `invoke` | M4 |

---

## ModelProvider

`contracts/src/personalai_contracts/ports/model_provider.py`

### Responsibility

An OpenAI-compatible abstraction over a model runtime (local or remote). Concrete adapters
(Ollama, llama.cpp, vLLM, remote via LiteLLM) implement this and are selected through the
provider registry (M0-4). Streaming is intentionally omitted at M0-2 and added in M1.

### Protocol

```python
@runtime_checkable
class ModelProvider(Protocol):
    name: str

    def capabilities(self, model: str) -> ModelCapabilities: ...
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...
    async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult: ...
```

### Value objects

| Type | Kind | Fields |
|---|---|---|
| `Role` | `StrEnum` | `SYSTEM`, `USER`, `ASSISTANT`, `TOOL` |
| `ChatMessage` | frozen dataclass | `role: Role`, `content: str` (multimodal parts arrive M8) |
| `ModelCapabilities` | frozen dataclass | `text=True`, `vision=False`, `embeddings=False`, `tool_calling=False`, `structured_output=False`, `max_context_tokens: int | None = None` |
| `GenerationRequest` | frozen dataclass | `messages: Sequence[ChatMessage]`, `model: str`, `temperature: float | None = None`, `max_tokens: int | None = None`, `json_schema: Mapping[str, Any] | None = None` |
| `GenerationResult` | frozen dataclass | `text: str`, `model: str`, `finish_reason: str | None = None`, `usage: Mapping[str, int] = {}` |
| `EmbeddingResult` | frozen dataclass | `vectors: Sequence[Sequence[float]]`, `model: str`, `dimensions: int` |

`GenerationRequest.json_schema` requests structured output constrained to that JSON Schema,
validated by the structured-output layer (M0-3) — see
[ADR-0003](../architecture/adr/0003-structured-output-first.md). `capabilities()` is cheap and
cacheable; the router uses it for capability-based routing.

### Minimal adapter

```python
from collections.abc import Sequence

from personalai_contracts.ports.model_provider import (
    EmbeddingResult, GenerationRequest, GenerationResult, ModelCapabilities,
)


class StaticProvider:
    """Smallest valid ModelProvider — replace bodies with a real runtime client."""

    name = "static"

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(text=True)

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(text="hello", model=request.model, finish_reason="stop")

    async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
        return EmbeddingResult(vectors=[[0.0] for _ in texts], model=model, dimensions=1)
```

---

## Retriever

`contracts/src/personalai_contracts/ports/retriever.py`

### Responsibility

A retrieval strategy (vector, keyword, or graph/KAG) that, given a query, returns ranked results
**with citations** so answers stay explainable
([ADR-0003](../architecture/adr/0003-structured-output-first.md),
[ADR-0005](../architecture/adr/0005-postgres-pgvector-storage.md)). Strategies are registered
with the core (M0-4) and invoked by the orchestrator.

### Protocol

```python
@runtime_checkable
class Retriever(Protocol):
    name: str

    async def retrieve(self, query: RetrievalQuery) -> Sequence[RetrievedItem]: ...
```

`retrieve` returns results highest-score-first.

### Value objects

| Type | Kind | Fields |
|---|---|---|
| `RetrievalQuery` | frozen dataclass | `text: str`, `top_k: int = 5`, `filters: Mapping[str, Any] = {}` |
| `Citation` | frozen dataclass | `source_id: str`, `locator: str | None = None` |
| `RetrievedItem` | frozen dataclass | `content: str`, `score: float`, `citation: Citation`, `metadata: Mapping[str, Any] = {}` |

### Minimal adapter

```python
from collections.abc import Sequence

from personalai_contracts.ports.retriever import RetrievalQuery, RetrievedItem


class FirstNRetriever:
    name = "first-n"

    def __init__(self, items: Sequence[RetrievedItem]) -> None:
        self._items = list(items)

    async def retrieve(self, query: RetrievalQuery) -> Sequence[RetrievedItem]:
        ranked = sorted(self._items, key=lambda i: i.score, reverse=True)
        return ranked[: query.top_k]
```

---

## Storage repositories

`contracts/src/personalai_contracts/ports/storage.py`

### Responsibility

The repository interfaces for the storage spine
([ADR-0005](../architecture/adr/0005-postgres-pgvector-storage.md)): a generic relational
repository, a vector repository, an object store, and a graph-store stub (KAG, M10). Concrete
adapters (postgres, pgvector, qdrant, object-store, neo4j/age) are selected via dependency
injection (M0-4). All methods are async.

### `Repository[T]`

A generic, id-addressable repository for entities of type `T` (uses PEP 695 generics).

```python
@runtime_checkable
class Repository[T](Protocol):
    async def add(self, entity: T) -> None: ...
    async def get(self, entity_id: str) -> T | None: ...
    async def list(self) -> Sequence[T]: ...
    async def delete(self, entity_id: str) -> None: ...
```

### `VectorRepository`

```python
@runtime_checkable
class VectorRepository(Protocol):
    async def upsert(self, records: Sequence[VectorRecord]) -> None: ...
    async def query(self, vector: Sequence[float], top_k: int = 5) -> Sequence[VectorMatch]: ...
    async def delete(self, ids: Sequence[str]) -> None: ...
```

| Type | Fields |
|---|---|
| `VectorRecord` | `id: str`, `vector: Sequence[float]`, `metadata: Mapping[str, Any] = {}` |
| `VectorMatch` | `id: str`, `score: float`, `metadata: Mapping[str, Any] = {}` |

### `ObjectStore`

Encrypted-at-rest blob storage for files/artifacts.

```python
@runtime_checkable
class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str | None = None) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...
    async def delete(self, key: str) -> None: ...
```

### `GraphStore`

Graph/KAG store stub (optional, M10) — a minimal edge + neighbour interface.

```python
@runtime_checkable
class GraphStore(Protocol):
    async def add_edge(self, src: str, relation: str, dst: str) -> None: ...
    async def neighbors(self, node: str) -> Sequence[str]: ...
```

### Minimal `Repository` adapter

```python
from collections.abc import Sequence


class DictRepository[T]:
    def __init__(self, id_of: "Callable[[T], str]") -> None:
        self._id_of = id_of
        self._store: dict[str, T] = {}

    async def add(self, entity: T) -> None:
        self._store[self._id_of(entity)] = entity

    async def get(self, entity_id: str) -> T | None:
        return self._store.get(entity_id)

    async def list(self) -> Sequence[T]:
        return list(self._store.values())

    async def delete(self, entity_id: str) -> None:
        self._store.pop(entity_id, None)
```

(See `InMemoryRepository` in the fakes for the canonical reference.)

---

## ModalityHandler

`contracts/src/personalai_contracts/ports/modality.py`

### Responsibility

Normalizes a piece of media into text/structured content for the omni-capability pipeline. The
base port covers parsing/ingestion; specialized handlers (OCR, STT, TTS, render) are added as
adapters from M3/M8. **Implementations must sandbox parsing** — media is untrusted input (see the
[threat model](../architecture/THREAT-MODEL.md)).

### Protocol

```python
@runtime_checkable
class ModalityHandler(Protocol):
    kind: ModalityKind

    def can_handle(self, mime_type: str) -> bool: ...
    async def parse(self, ref: MediaRef) -> ParsedContent: ...
```

### Value objects

| Type | Kind | Fields |
|---|---|---|
| `ModalityKind` | `StrEnum` | `TEXT`, `IMAGE`, `AUDIO`, `VIDEO`, `DOCUMENT` |
| `MediaRef` | frozen dataclass | `kind: ModalityKind`, `uri: str`, `mime_type: str | None = None` (untrusted) |
| `ParsedContent` | frozen dataclass | `text: str`, `metadata: Mapping[str, Any] = {}` |

### Minimal adapter

```python
from personalai_contracts.ports.modality import (
    MediaRef, ModalityKind, ParsedContent,
)


class PlainTextHandler:
    kind = ModalityKind.TEXT

    def can_handle(self, mime_type: str) -> bool:
        return mime_type.startswith("text/")

    async def parse(self, ref: MediaRef) -> ParsedContent:
        # Real handlers read + sandbox the bytes at ref.uri.
        return ParsedContent(text="...", metadata={"kind": ref.kind.value})
```

---

## AgentRole and AgentNode

`contracts/src/personalai_contracts/ports/agent.py`

### Responsibility

An `AgentNode` is a single step in an orchestration graph (LangGraph-style): it maps an input
state to an output state. An `AgentRole` is a named, described capability that exposes such a
node. Typed agent-message envelopes that flow as state are defined as schemas in **M0-3**;
orchestration wiring is **M6**.

### Protocols

```python
AgentState = Mapping[str, Any]  # opaque, schema-validated; M0-3 refines its shape


@runtime_checkable
class AgentNode(Protocol):
    name: str

    async def run(self, state: AgentState, context: AgentContext) -> AgentState: ...


@runtime_checkable
class AgentRole(Protocol):
    name: str
    description: str

    def node(self) -> AgentNode: ...
```

| Type | Kind | Fields |
|---|---|---|
| `AgentContext` | frozen dataclass | `conversation_id: str`, `metadata: Mapping[str, Any] = {}` |
| `AgentState` | type alias | `Mapping[str, Any]` |

### Minimal adapter

```python
from personalai_contracts.ports.agent import AgentContext, AgentNode, AgentState


class TagNode:
    name = "tagger"

    async def run(self, state: AgentState, context: AgentContext) -> AgentState:
        return {**state, "tagged_by": self.name, "conversation_id": context.conversation_id}


class TagRole:
    name = "tagger"
    description = "Adds a tag to the state"

    def node(self) -> AgentNode:
        return TagNode()
```

---

## ToolHandler

`contracts/src/personalai_contracts/ports/tool.py`

### Responsibility

The execution contract for a single tool or MCP server action. The full tool/MCP **manifest**
(provenance, permissions, I/O schemas, egress, risk, signature) is defined as a schema in
**M0-3**; permission enforcement and sandboxing live in the Tool/MCP gateway (**M4**). Tool
handlers are **never invoked directly by agents** — only through the gateway
([ADR-0004](../architecture/adr/0004-tool-mcp-gateway-sandbox.md)). The `ToolInvocation` and
`ToolManifest` schema contracts (provenance, permissions, egress, risk) are documented in the
[structured-output schemas reference](./structured-output-schemas.md#the-contracts).

### Protocol

```python
@runtime_checkable
class ToolHandler(Protocol):
    name: str

    async def invoke(self, call: ToolCall) -> ToolResult: ...
```

| Type | Kind | Fields |
|---|---|---|
| `ToolCall` | frozen dataclass | `tool: str`, `version: str`, `args: Mapping[str, Any] = {}` (mirrors the M0-3 tool-invocation contract) |
| `ToolResult` | frozen dataclass | `ok: bool`, `output: Mapping[str, Any] = {}`, `error: str | None = None` |

`ToolResult` is **fail-closed**: on error, return `ok=False` and an `error` string rather than
raising past the gateway.

### Minimal adapter

```python
from personalai_contracts.ports.tool import ToolCall, ToolResult


class PingTool:
    name = "ping"

    async def invoke(self, call: ToolCall) -> ToolResult:
        try:
            return ToolResult(ok=True, output={"pong": call.args.get("msg", "")})
        except Exception as exc:  # fail closed
            return ToolResult(ok=False, error=str(exc))
```

---

## Reference fakes (test doubles)

`contracts/src/personalai_contracts/testing/fakes.py` (re-exported from
`personalai_contracts.testing`)

These are deterministic, in-memory implementations of **every** port. They exist to prove the
ports are implementable and to back unit tests across packages (e.g. agent/orchestration tests
can use `FakeModelProvider`). They are **not production adapters** and depend only on the ports.

| Fake | Implements | Behaviour |
|---|---|---|
| `FakeModelProvider` | `ModelProvider` | `generate` echoes the last user message (`"echo: ..."`); `embed` returns stable 8-dim content-derived vectors; capabilities are configurable. |
| `FakeRetriever` | `Retriever` | Returns preloaded items sorted by score, truncated to `top_k`. |
| `InMemoryRepository[T]` | `Repository[T]` | Dict-backed, keyed by a caller-supplied `id_getter`. |
| `InMemoryVectorRepository` | `VectorRepository` | Ranks by dot-product similarity. |
| `InMemoryObjectStore` | `ObjectStore` | Dict-backed blob store. |
| `InMemoryGraphStore` | `GraphStore` | Adjacency-list KAG stub. |
| `EchoModalityHandler` | `ModalityHandler` | Handles `text/*`; returns the `MediaRef.uri` as parsed text. |
| `EchoAgentNode` / `EchoAgentRole` | `AgentNode` / `AgentRole` | Records that the node ran into the state. |
| `EchoToolHandler` | `ToolHandler` | Echoes `tool` + `args` back as `ok=True` output. |

### Using a fake in a test

The contracts tests avoid an async test-plugin dependency by driving coroutines with
`asyncio.run` (see `contracts/tests/test_ports.py`):

```python
import asyncio

from personalai_contracts.ports.model_provider import (
    ChatMessage, GenerationRequest, Role,
)
from personalai_contracts.ports import ModelProvider
from personalai_contracts.testing import FakeModelProvider


def test_my_feature_with_a_fake_provider() -> None:
    provider = FakeModelProvider()
    assert isinstance(provider, ModelProvider)  # @runtime_checkable structural check

    result = asyncio.run(
        provider.generate(
            GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="m")
        )
    )
    assert result.text == "echo: hi"
```

---

## How to add an adapter

The seam workflow follows the **golden rule** from the architecture report
([§22.1](../architecture/PersonalAI-Architecture-Research.md#221-the-modularity-rule-read-this-first)):

> New capability = a new adapter behind an existing port + a registry entry + a schema. The core
> stays stable.

Concretely:

1. **Pick the seam.** Find the port your feature belongs behind (table above, and
   [§22.2](../architecture/PersonalAI-Architecture-Research.md#222-the-seams-stable-extension-points)).
   If no port fits, that is an architecture change — open an ADR; do not widen the core ad hoc.
2. **Implement the port.** Create a new package/folder per the planned layout
   (`/providers/*`, `/retrieval/*`, `/storage/*`, `/modalities/*`, `/tools/*`, `/agents/*`).
   Import **only** from `personalai_contracts`. Do not import sibling adapters.
3. **Declare its schema** (M0-3). Add/extend the versioned schema (`$id` + semver) for any data
   the adapter produces or consumes; validate at the boundary
   ([ADR-0003](../architecture/adr/0003-structured-output-first.md)). Tools/MCP additionally ship
   a manifest.
4. **Register it** (M0-4). Add the adapter to the appropriate registry so the FastAPI app can
   select it via dependency injection. Until M0-4 lands, registration is a documented placeholder.
5. **Add tests.** Assert `isinstance(adapter, ThePort)` for the structural check, then exercise
   behaviour with `asyncio.run`. Reuse the in-memory fakes for collaborators. Keep coverage at or
   above the gate (`fail_under = 90`).
6. **Run the checks.** `make check` (lint + types + tests + architecture). The architecture check
   (`import-linter`) fails if your adapter imports outward or sideways.

What you should **not** touch: the orchestrator, the gateway, the storage interfaces, or the
message contracts. If you find yourself editing those to add a feature, stop and reconsider the
seam — see [coding-standards.md](../development/coding-standards.md).

## Related

- [Coding standards & conventions](../development/coding-standards.md)
- [Toolchain & monorepo](../development/toolchain.md)
- [ADR-0001 — modular monolith + hexagonal](../architecture/adr/0001-modular-monolith-hexagonal.md)
- [ADR-0003 — structured-output-first](../architecture/adr/0003-structured-output-first.md)
- [ADR-0004 — tool/MCP gateway + sandbox](../architecture/adr/0004-tool-mcp-gateway-sandbox.md)
- [ADR-0005 — Postgres + pgvector storage](../architecture/adr/0005-postgres-pgvector-storage.md)
- [Architecture report §22 — modular implementation roadmap](../architecture/PersonalAI-Architecture-Research.md#22-modular-implementation-roadmap)

## Last updated notes

- 2026-06-05: Initial reference for the M0-2 ports and fakes. Schemas (M0-3), registries/DI
  (M0-4), and streaming (M1) are referenced as upcoming, not documented as existing.
