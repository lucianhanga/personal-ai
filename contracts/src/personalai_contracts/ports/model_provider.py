"""Port: model provider.

An OpenAI-compatible abstraction over a model runtime (local or remote). Concrete
adapters (Ollama, llama.cpp, vLLM, remote via LiteLLM) implement this Protocol and are
registered with the core registry (M0-4). Adapters never import each other (ADR-0001).

Streaming is intentionally omitted at M0-2 and added in M1 alongside chat.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class Role(StrEnum):
    """The author of a chat message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class ChatMessage:
    """A single chat turn. Multimodal parts are added in M8."""

    role: Role
    content: str


@dataclass(frozen=True)
class ModelCapabilities:
    """What a given model can do, used by the router for capability-based routing."""

    text: bool = True
    vision: bool = False
    embeddings: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    thinking: bool = False
    max_context_tokens: int | None = None


@dataclass(frozen=True)
class GenerationRequest:
    """A request to generate a completion.

    ``json_schema`` requests structured output constrained to that JSON Schema
    (validated by the structured-output layer, M0-3).
    """

    messages: Sequence[ChatMessage]
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    json_schema: Mapping[str, Any] | None = None
    think: bool | None = None
    """Control a thinking/reasoning model's reasoning trace (None = the model's default)."""


@dataclass(frozen=True)
class GenerationResult:
    """The result of a (non-streaming) generation."""

    text: str
    model: str
    finish_reason: str | None = None
    thinking: str | None = None
    usage: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationChunk:
    """One streamed increment of a generation."""

    delta: str = ""
    thinking: str | None = None
    done: bool = False
    finish_reason: str | None = None


@dataclass(frozen=True)
class EmbeddingResult:
    """Embedding vectors for one or more inputs."""

    vectors: Sequence[Sequence[float]]
    model: str
    dimensions: int


@runtime_checkable
class ModelProvider(Protocol):
    """A model runtime that can detect capabilities, generate, and embed."""

    name: str

    async def capabilities(self, model: str) -> ModelCapabilities:
        """Return the capabilities of ``model`` (may query the runtime; cache as needed)."""
        ...

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate a completion for ``request``."""
        ...

    def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        """Stream a completion for ``request`` as incremental chunks."""
        ...

    async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
        """Embed ``texts`` with ``model``."""
        ...
