"""Reference in-memory fakes for every port (test doubles, not production adapters)."""

from personalai_contracts.testing.fakes import (
    EchoAgentNode,
    EchoAgentRole,
    EchoModalityHandler,
    EchoToolHandler,
    FakeModelProvider,
    FakeRetriever,
    InMemoryGraphStore,
    InMemoryObjectStore,
    InMemoryRepository,
    InMemoryVectorRepository,
)

__all__ = [
    "EchoAgentNode",
    "EchoAgentRole",
    "EchoModalityHandler",
    "EchoToolHandler",
    "FakeModelProvider",
    "FakeRetriever",
    "InMemoryGraphStore",
    "InMemoryObjectStore",
    "InMemoryRepository",
    "InMemoryVectorRepository",
]
