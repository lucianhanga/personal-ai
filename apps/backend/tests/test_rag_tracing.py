"""LangSmith/LangChain tracing must be provably OFF (#420 CISO review) -- no DB, no network.

langchain-core pulls langsmith transitively. The in-process egress guard does NOT contain
langsmith's own httpx client, so containment relies on the tracing env staying disabled. These
tests assert the defensive force-disable holds even when an inherited environment tries to enable
tracing, and that importing/using the langchain-core retriever path triggers no non-loopback egress.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence

import pytest

from personalai_backend.rag import HybridVectorStoreRetriever, ProviderEmbeddings
from personalai_backend.rag.tracing import (
    _TRACING_ENDPOINT_VARS,
    _TRACING_FLAGS,
    disable_langchain_tracing,
)
from personalai_contracts.ports import VectorMatch
from personalai_contracts.ports.storage import GLOBAL_SCOPE, Scope
from personalai_contracts.testing import FakeModelProvider, InMemoryVectorRepository


def test_disable_langchain_tracing_forces_flags_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even if an inherited env enabled tracing + set an endpoint/key, startup forces it all off."""
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-should-be-dropped")

    disable_langchain_tracing()

    for flag in _TRACING_FLAGS:
        assert os.environ[flag] == "false"
    for var in _TRACING_ENDPOINT_VARS:
        assert var not in os.environ


def test_disable_langchain_tracing_sets_flags_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """A clean env still gets explicit false flags (no silent default-on path)."""
    for flag in _TRACING_FLAGS:
        monkeypatch.delenv(flag, raising=False)
    disable_langchain_tracing()
    for flag in _TRACING_FLAGS:
        assert os.environ[flag] == "false"


def test_create_app_disables_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_app() force-disables tracing on every boot (the testable seam, not the entrypoint)."""
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    from personalai_backend.app import create_app

    create_app()
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
    assert os.environ["LANGSMITH_TRACING"] == "false"


class _FakeVectors(InMemoryVectorRepository):
    async def hybrid_query(
        self,
        vector: Sequence[float],
        text: str,
        top_k: int = 5,
        *,
        scope: Scope = GLOBAL_SCOPE,
        union_conversation_id: str | None = None,
    ) -> Sequence[VectorMatch]:
        return [VectorMatch(id="v1", score=0.5, metadata={"text": "t", "document_id": "d"})]


def test_retrieval_path_makes_no_non_loopback_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    """A full langchain-core retriever run must open no non-loopback socket (no LangSmith call).

    We trip a tripwire on socket.create_connection: any attempt to reach a non-loopback host fails
    the test. Embeddings and storage are fakes, so a clean run touches no socket at all.
    """
    import socket

    real_create_connection = socket.create_connection
    attempts: list[tuple[str, int]] = []

    def _guarded(address: tuple[str, int], *args: object, **kwargs: object) -> object:
        host, port = address[0], address[1]
        attempts.append((host, port))
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"non-loopback egress attempted to {host}:{port}")
        return real_create_connection(address, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(socket, "create_connection", _guarded)

    retriever = HybridVectorStoreRetriever(
        vectors=_FakeVectors(),
        embeddings=ProviderEmbeddings(FakeModelProvider(), "embed-model"),
        top_k=3,
    )
    docs = asyncio.run(retriever.ainvoke("question"))
    assert len(docs) == 1
    # The fakes never open a socket; the assertion above would have fired on any non-loopback host.
    assert all(h in ("127.0.0.1", "::1", "localhost") for h, _ in attempts)
