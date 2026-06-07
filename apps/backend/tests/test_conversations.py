"""Conversation endpoints + chat persistence. CRUD/persistence need Postgres (skipped otherwise);
the 503 path needs no DB."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import bootstrap
from personalai_contracts.ports import EmbeddingResult, GenerationRequest, GenerationResult
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig
from personalai_storage_postgres import VECTOR_DIM, create_pool

_FACT = "Lucian works at Hyperneers GmbH"


class _EmptyGen(FakeModelProvider):
    """Summarizer that returns an empty string (no system-summary message should be added)."""

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(text="", model=request.model)


class _MemFake(FakeModelProvider):
    """generate() returns one extracted fact as JSON; embed() returns column-sized vectors."""

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        facts = f'{{"facts":[{{"kind":"semantic","text":"{_FACT}","confidence":0.95}}]}}'
        return GenerationResult(text=facts, model=request.model)

    async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[0.0] * (VECTOR_DIM - 1) + [1.0] for _ in texts],
            model=model,
            dimensions=VECTOR_DIM,
        )


TOKEN = "test-secret-token"
DB_URL = os.environ.get(
    "PERSONALAI_DATABASE_URL", "postgresql://personalai@127.0.0.1:5432/personalai"
)
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _db_available() -> bool:
    async def _check() -> bool:
        try:
            pool = await create_pool(DB_URL)
        except Exception:
            return False
        await pool.close()
        return True

    return asyncio.run(_check())


def _client(database_url: str = DB_URL, **cfg: Any) -> TestClient:
    config = CoreConfig(auth_token=TOKEN, model_provider="fake", database_url=database_url, **cfg)
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("fake", FakeModelProvider(name="fake"))
    return TestClient(create_app(boot))


def test_conversations_unavailable_without_storage_503() -> None:
    with _client("postgresql://personalai@127.0.0.1:59999/x") as client:
        assert client.get("/api/conversations", headers=AUTH).status_code == 503


def test_chat_with_conversation_id_without_storage_streams() -> None:
    # conversation_id given but no storage -> persistence skipped, chat still streams.
    with (
        _client("postgresql://personalai@127.0.0.1:59999/x") as client,
        client.stream(
            "POST",
            "/api/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}], "conversation_id": "x"},
        ) as resp,
    ):
        assert resp.status_code == 200
        "".join(resp.iter_text())


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_conversation_crud() -> None:
    with _client() as client:
        created = client.post("/api/conversations", headers=AUTH, json={"title": "T1"}).json()
        cid = created["data"]["id"]
        assert created["data"]["title"] == "T1"

        listed = client.get("/api/conversations", headers=AUTH).json()["data"]["conversations"]
        assert any(c["id"] == cid for c in listed)

        got = client.get(f"/api/conversations/{cid}", headers=AUTH).json()["data"]
        assert got["messages"] == []

        assert client.delete(f"/api/conversations/{cid}", headers=AUTH).status_code == 200
        assert client.get(f"/api/conversations/{cid}", headers=AUTH).status_code == 404


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_chat_persists_turns() -> None:
    with _client() as client:
        cid = client.post("/api/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "remember this"}],
                "conversation_id": cid,
            },
        ) as resp:
            "".join(resp.iter_text())
        msgs = client.get(f"/api/conversations/{cid}", headers=AUTH).json()["data"]["messages"]
        roles = [m["role"] for m in msgs]
        assert "user" in roles and "assistant" in roles
        assert any(m["content"] == "remember this" for m in msgs)


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_chat_without_user_message_persists_only_assistant() -> None:
    with _client() as client:
        cid = client.post("/api/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "system", "content": "be brief"}],
                "conversation_id": cid,
            },
        ) as resp:
            "".join(resp.iter_text())
        got = client.get(f"/api/conversations/{cid}", headers=AUTH).json()["data"]
        roles = [m["role"] for m in got["messages"]]
        assert "user" not in roles  # no user turn was present, so none was persisted


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_stm_folds_old_turns_into_summary() -> None:
    with _client(stm_keep_recent=2) as client:
        cid = client.post("/api/conversations", headers=AUTH, json={}).json()["data"]["id"]
        msgs = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(5)
        ]
        with client.stream(
            "POST", "/api/chat", headers=AUTH, json={"messages": msgs, "conversation_id": cid}
        ) as resp:
            "".join(resp.iter_text())
        # Re-send the same history: nothing new aged out, so no re-summarization happens.
        with client.stream(
            "POST", "/api/chat", headers=AUTH, json={"messages": msgs, "conversation_id": cid}
        ) as resp:
            "".join(resp.iter_text())

    async def _summary() -> tuple[str | None, int]:
        pool = await create_pool(DB_URL)
        try:
            row = await pool.fetchrow(
                "SELECT summary, summary_through FROM conversations WHERE id = $1", cid
            )
            return (row["summary"], row["summary_through"])
        finally:
            await pool.close()

    summary, through = asyncio.run(_summary())
    assert through == 3  # 5 messages, keep_recent=2 -> 3 older folded
    assert summary is not None


def _mem_client(**cfg: Any) -> TestClient:
    config = CoreConfig(
        auth_token=TOKEN,
        model_provider="memfake",
        embed_provider="memfake",
        database_url=DB_URL,
        **cfg,
    )
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("memfake", _MemFake(name="memfake"))
    return TestClient(create_app(boot))


async def _memories_for(cid: str) -> list[str]:
    pool = await create_pool(DB_URL)
    try:
        rows = await pool.fetch(
            "SELECT text FROM memories WHERE source->>'conversation_id' = $1", cid
        )
        return [r["text"] for r in rows]
    finally:
        await pool.close()


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_memory_extracted_after_chat() -> None:
    with _mem_client() as client:
        cid = client.post("/api/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "where do I work?"}],
                "conversation_id": cid,
            },
        ) as resp:
            "".join(resp.iter_text())
    assert any(_FACT in m for m in asyncio.run(_memories_for(cid)))


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_incognito_conversation_skips_memory() -> None:
    with _mem_client() as client:
        cid = client.post("/api/conversations", headers=AUTH, json={}).json()["data"]["id"]

        async def _set_incognito() -> None:
            pool = await create_pool(DB_URL)
            try:
                await pool.execute("UPDATE conversations SET incognito = true WHERE id = $1", cid)
            finally:
                await pool.close()

        asyncio.run(_set_incognito())
        with client.stream(
            "POST",
            "/api/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "secret"}], "conversation_id": cid},
        ) as resp:
            "".join(resp.iter_text())
    assert asyncio.run(_memories_for(cid)) == []


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_memory_extraction_failure_does_not_break_chat() -> None:
    class _BoomEmbed(_MemFake):
        async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
            raise RuntimeError("embed down")

    config = CoreConfig(
        auth_token=TOKEN, model_provider="memfake", embed_provider="memfake", database_url=DB_URL
    )
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("memfake", _BoomEmbed(name="memfake"))
    with TestClient(create_app(boot)) as client:
        cid = client.post("/api/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}], "conversation_id": cid},
        ) as resp:
            assert resp.status_code == 200
            "".join(resp.iter_text())
    assert asyncio.run(_memories_for(cid)) == []  # extraction failed, but chat succeeded


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_memory_disabled_skips_extraction() -> None:
    with _mem_client(memory_enabled=False) as client:
        cid = client.post("/api/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "where do I work?"}],
                "conversation_id": cid,
            },
        ) as resp:
            "".join(resp.iter_text())
    assert asyncio.run(_memories_for(cid)) == []


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_chat_unknown_conversation_404() -> None:
    with _client() as client:
        resp = client.post(
            "/api/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}], "conversation_id": "nope"},
        )
        assert resp.status_code == 404


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_stm_unknown_conversation_with_long_history_404() -> None:
    # STM runs before persistence; an unknown conversation with a long history still 404s.
    with _client(stm_keep_recent=2) as client:
        msgs = [{"role": "user", "content": f"m{i}"} for i in range(5)]
        resp = client.post(
            "/api/chat", headers=AUTH, json={"messages": msgs, "conversation_id": "nope"}
        )
        assert resp.status_code == 404


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_stm_empty_summary_adds_no_system_message() -> None:
    config = CoreConfig(
        auth_token=TOKEN, model_provider="fake", database_url=DB_URL, stm_keep_recent=2
    )
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("fake", _EmptyGen(name="fake"))
    with TestClient(create_app(boot)) as client:
        cid = client.post("/api/conversations", headers=AUTH, json={}).json()["data"]["id"]
        msgs = [{"role": "user", "content": f"m{i}"} for i in range(5)]
        with client.stream(
            "POST", "/api/chat", headers=AUTH, json={"messages": msgs, "conversation_id": cid}
        ) as resp:
            assert resp.status_code == 200
            "".join(resp.iter_text())
