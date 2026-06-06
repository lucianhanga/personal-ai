"""Each in-memory fake satisfies its port Protocol and behaves correctly.

This proves the ports (M0-2) are implementable and gives the fakes coverage. Async methods
are driven with ``asyncio.run`` to avoid an async test-plugin dependency.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from personalai_contracts.ports import (
    AgentNode,
    AgentRole,
    ChatMessage,
    GenerationRequest,
    GraphStore,
    MediaRef,
    ModalityHandler,
    ModalityKind,
    ModelProvider,
    Repository,
    RetrievalQuery,
    RetrievedItem,
    Retriever,
    Role,
    ToolCall,
    ToolHandler,
    VectorRecord,
    VectorRepository,
)
from personalai_contracts.ports.agent import AgentContext
from personalai_contracts.ports.retriever import Citation
from personalai_contracts.ports.storage import ObjectStore
from personalai_contracts.testing import (
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


def test_model_provider() -> None:
    provider = FakeModelProvider()
    assert isinstance(provider, ModelProvider)
    assert asyncio.run(provider.capabilities("m")).text is True

    result = asyncio.run(
        provider.generate(GenerationRequest(messages=[ChatMessage(Role.USER, "hi")], model="m"))
    )
    assert result.text == "echo: hi"
    assert result.model == "m"

    emb = asyncio.run(provider.embed(["abc", "de"], "m"))
    assert emb.dimensions == 8
    assert len(emb.vectors) == 2
    assert all(len(v) == 8 for v in emb.vectors)


def test_retriever() -> None:
    items = [
        RetrievedItem("low", 0.1, Citation("s1")),
        RetrievedItem("high", 0.9, Citation("s2", locator="p1")),
    ]
    retriever = FakeRetriever(items)
    assert isinstance(retriever, Retriever)

    top = asyncio.run(retriever.retrieve(RetrievalQuery("q", top_k=1)))
    assert len(top) == 1
    assert top[0].content == "high"


def test_generic_repository() -> None:
    @dataclass(frozen=True)
    class Item:
        id: str
        name: str

    repo: InMemoryRepository[Item] = InMemoryRepository(id_getter=lambda i: i.id)
    assert isinstance(repo, Repository)

    asyncio.run(repo.add(Item("1", "a")))
    asyncio.run(repo.add(Item("2", "b")))
    assert asyncio.run(repo.get("1")) == Item("1", "a")
    assert len(asyncio.run(repo.list())) == 2
    asyncio.run(repo.delete("1"))
    assert asyncio.run(repo.get("1")) is None


def test_vector_repository() -> None:
    repo = InMemoryVectorRepository()
    assert isinstance(repo, VectorRepository)

    asyncio.run(
        repo.upsert(
            [
                VectorRecord("a", [1.0, 0.0], {"k": "a"}),
                VectorRecord("b", [0.0, 1.0], {"k": "b"}),
            ]
        )
    )
    matches = asyncio.run(repo.query([1.0, 0.0], top_k=2))
    assert matches[0].id == "a"
    assert matches[0].score >= matches[1].score

    asyncio.run(repo.delete(["a"]))
    assert all(m.id != "a" for m in asyncio.run(repo.query([1.0, 0.0])))


def test_object_store() -> None:
    store = InMemoryObjectStore()
    assert isinstance(store, ObjectStore)

    asyncio.run(store.put("k", b"data", content_type="text/plain"))
    assert asyncio.run(store.exists("k")) is True
    assert asyncio.run(store.get("k")) == b"data"
    asyncio.run(store.delete("k"))
    assert asyncio.run(store.exists("k")) is False


def test_graph_store() -> None:
    graph = InMemoryGraphStore()
    assert isinstance(graph, GraphStore)

    asyncio.run(graph.add_edge("x", "rel", "y"))
    asyncio.run(graph.add_edge("x", "rel", "z"))
    assert set(asyncio.run(graph.neighbors("x"))) == {"y", "z"}
    assert asyncio.run(graph.neighbors("none")) == []


def test_modality_handler() -> None:
    handler = EchoModalityHandler()
    assert isinstance(handler, ModalityHandler)
    assert handler.kind is ModalityKind.TEXT
    assert handler.can_handle("text/plain") is True
    assert handler.can_handle("image/png") is False

    parsed = asyncio.run(handler.parse(MediaRef(ModalityKind.TEXT, "hello.txt", "text/plain")))
    assert parsed.text == "hello.txt"


def test_agent_role_and_node() -> None:
    role = EchoAgentRole()
    assert isinstance(role, AgentRole)
    node = role.node()
    assert isinstance(node, AgentNode)

    out = asyncio.run(node.run({"in": 1}, AgentContext(conversation_id="c1")))
    assert out["ran"] == "echo"
    assert out["conversation_id"] == "c1"
    assert out["in"] == 1


def test_tool_handler() -> None:
    handler = EchoToolHandler()
    assert isinstance(handler, ToolHandler)

    result = asyncio.run(handler.invoke(ToolCall(tool="t", version="1", args={"a": 1})))
    assert result.ok is True
    assert result.output["tool"] == "t"
    assert result.output["args"] == {"a": 1}
