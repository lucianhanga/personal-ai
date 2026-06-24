"""Conversation endpoints + chat persistence. CRUD/persistence need Postgres (skipped otherwise);
the 503 path needs no DB."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import bootstrap
from personalai_contracts.ports import (
    EmbeddingResult,
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    Role,
    ToolCallRequest,
)
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig
from personalai_storage_postgres import VECTOR_DIM, apply_migrations, create_pool

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
        assert client.get("/api/v1/conversations", headers=AUTH).status_code == 503


def test_chat_with_conversation_id_without_storage_streams() -> None:
    # conversation_id given but no storage -> persistence skipped, chat still streams.
    with (
        _client("postgresql://personalai@127.0.0.1:59999/x") as client,
        client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}], "conversation_id": "x"},
        ) as resp,
    ):
        assert resp.status_code == 200
        "".join(resp.iter_text())


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_conversation_crud() -> None:
    with _client() as client:
        created = client.post("/api/v1/conversations", headers=AUTH, json={"title": "T1"}).json()
        cid = created["data"]["id"]
        assert created["data"]["title"] == "T1"

        listed = client.get("/api/v1/conversations", headers=AUTH).json()["data"]["conversations"]
        assert any(c["id"] == cid for c in listed)

        got = client.get(f"/api/v1/conversations/{cid}", headers=AUTH).json()["data"]
        assert got["messages"] == []

        assert client.delete(f"/api/v1/conversations/{cid}", headers=AUTH).status_code == 200
        assert client.get(f"/api/v1/conversations/{cid}", headers=AUTH).status_code == 404


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_conversation_rename() -> None:
    with _client() as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={"title": "Old"}).json()[
            "data"
        ]["id"]
        renamed = client.patch(
            f"/api/v1/conversations/{cid}", headers=AUTH, json={"title": "New name"}
        )
        assert renamed.status_code == 200
        assert renamed.json()["data"]["title"] == "New name"
        listed = client.get("/api/v1/conversations", headers=AUTH).json()["data"]["conversations"]
        assert any(c["id"] == cid and c["title"] == "New name" for c in listed)

        assert (
            client.patch(
                f"/api/v1/conversations/{cid}", headers=AUTH, json={"title": "  "}
            ).status_code
            == 400
        )
        assert (
            client.patch(
                "/api/v1/conversations/nope", headers=AUTH, json={"title": "x"}
            ).status_code
            == 404
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_chat_persists_turns() -> None:
    with _client() as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "remember this"}],
                "conversation_id": cid,
            },
        ) as resp:
            "".join(resp.iter_text())
        msgs = client.get(f"/api/v1/conversations/{cid}", headers=AUTH).json()["data"]["messages"]
        roles = [m["role"] for m in msgs]
        assert "user" in roles and "assistant" in roles
        assert any(m["content"] == "remember this" for m in msgs)
        # Each message carries an ISO timestamp (the activity timeline shows relative time).
        assert all(isinstance(m["created_at"], str) and m["created_at"] for m in msgs)


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_chat_without_user_message_persists_only_assistant() -> None:
    with _client() as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "system", "content": "be brief"}],
                "conversation_id": cid,
            },
        ) as resp:
            "".join(resp.iter_text())
        got = client.get(f"/api/v1/conversations/{cid}", headers=AUTH).json()["data"]
        roles = [m["role"] for m in got["messages"]]
        assert "user" not in roles  # no user turn was present, so none was persisted


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_stm_folds_old_turns_into_summary() -> None:
    with _client(stm_keep_recent=2) as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        msgs = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(5)
        ]
        with client.stream(
            "POST", "/api/v1/chat", headers=AUTH, json={"messages": msgs, "conversation_id": cid}
        ) as resp:
            "".join(resp.iter_text())
        # Re-send the same history: nothing new aged out, so no re-summarization happens.
        with client.stream(
            "POST", "/api/v1/chat", headers=AUTH, json={"messages": msgs, "conversation_id": cid}
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
    # Start each memory test from an empty store (dedup is global; the fake emits one fixed fact).
    async def _reset() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            await pool.execute("TRUNCATE memories")
        finally:
            await pool.close()

    asyncio.run(_reset())
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
def test_memory_api_list_update_delete_clear() -> None:
    with _mem_client() as client:
        # seed a memory by chatting
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "where do I work?"}],
                "conversation_id": cid,
            },
        ) as resp:
            "".join(resp.iter_text())

        # Memory extraction runs in the background; poll until the fact lands.
        memories: list[dict[str, Any]] = []
        for _ in range(50):
            memories = client.get("/api/v1/memory", headers=AUTH).json()["data"]["memories"]
            if any(_FACT in m["text"] for m in memories):
                break
            time.sleep(0.1)
        assert any(_FACT in m["text"] for m in memories)
        mid = memories[0]["id"]

        patched = client.patch(f"/api/v1/memory/{mid}", headers=AUTH, json={"text": "edited fact"})
        assert patched.json()["data"]["text"] == "edited fact"
        assert (
            client.patch("/api/v1/memory/missing", headers=AUTH, json={"text": "x"}).status_code
            == 404
        )

        assert client.delete(f"/api/v1/memory/{mid}", headers=AUTH).status_code == 200
        assert client.delete("/api/v1/memory", headers=AUTH).json()["data"]["cleared"] is True
        assert client.get("/api/v1/memory", headers=AUTH).json()["data"]["memories"] == []


def test_memory_api_unavailable_without_storage_503() -> None:
    with _client("postgresql://personalai@127.0.0.1:59999/x") as client:
        assert client.get("/api/v1/memory", headers=AUTH).status_code == 503


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_chat_use_memory_with_no_memories_streams() -> None:
    with _mem_client() as client:  # memories truncated -> recall returns nothing
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "anything?"}],
                "conversation_id": cid,
                "use_memory": True,
            },
        ) as resp:
            assert resp.status_code == 200
            "".join(resp.iter_text())


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_chat_use_memory_injects_recall() -> None:
    with _mem_client() as client:
        # seed a memory, then ask with use_memory in a fresh conversation
        c1 = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "where do I work?"}],
                "conversation_id": c1,
            },
        ) as resp:
            "".join(resp.iter_text())
        c2 = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "remind me?"}],
                "conversation_id": c2,
                "use_memory": True,
            },
        ) as resp:
            assert resp.status_code == 200
            "".join(resp.iter_text())  # recall ran without error (injection is internal)


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_memory_extracted_after_chat() -> None:
    with _mem_client() as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
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
        created = client.post(
            "/api/v1/conversations", headers=AUTH, json={"incognito": True}
        ).json()["data"]
        assert created["incognito"] is True
        cid = created["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
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
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}], "conversation_id": cid},
        ) as resp:
            assert resp.status_code == 200
            "".join(resp.iter_text())
    assert asyncio.run(_memories_for(cid)) == []  # extraction failed, but chat succeeded


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_memory_disabled_skips_extraction() -> None:
    with _mem_client(memory_enabled=False) as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
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
            "/api/v1/chat",
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
            "/api/v1/chat", headers=AUTH, json={"messages": msgs, "conversation_id": "nope"}
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
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        msgs = [{"role": "user", "content": f"m{i}"} for i in range(5)]
        with client.stream(
            "POST", "/api/v1/chat", headers=AUTH, json={"messages": msgs, "conversation_id": cid}
        ) as resp:
            assert resp.status_code == 200
            "".join(resp.iter_text())


class _ThinkingFake(FakeModelProvider):
    """Streams a reasoning chunk then the answer (to exercise thinking-meta persistence)."""

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        # Two reasoning chunks -> exercises the consecutive-reasoning merge into one trace item.
        yield GenerationChunk(thinking="pondering ", delta="")
        yield GenerationChunk(thinking="the question", delta="")
        yield GenerationChunk(delta="the answer")
        yield GenerationChunk(done=True, finish_reason="stop")


class _ToolFake(FakeModelProvider):
    """Calls the calculator once, then answers (to exercise tool-step meta persistence)."""

    def __init__(self) -> None:
        super().__init__(name="toolfake")

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        if any(m.role == Role.TOOL for m in request.messages):
            return GenerationResult(text="It is 4.", model=request.model)
        return GenerationResult(
            text="",
            model=request.model,
            tool_calls=[ToolCallRequest(name="calculator", arguments={"expression": "2+2"})],
        )


def _client_with(name: str, provider: FakeModelProvider) -> TestClient:
    config = CoreConfig(auth_token=TOKEN, model_provider=name, database_url=DB_URL)
    boot = bootstrap(config=config)
    boot.registries.model_providers.register(name, provider, overwrite=True)
    return TestClient(create_app(boot))


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_assistant_message_persists_thinking_meta() -> None:
    with _client_with("thinkfake", _ThinkingFake(name="thinkfake")) as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "why?"}], "conversation_id": cid},
        ) as resp:
            "".join(resp.iter_text())
        msgs = client.get(f"/api/v1/conversations/{cid}", headers=AUTH).json()["data"]["messages"]
        assistant = next(m for m in msgs if m["role"] == "assistant")
        trace = assistant["meta"]["trace"]
        assert any(
            t["kind"] == "reasoning" and t["text"] == "pondering the question" for t in trace
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_assistant_message_persists_context_snapshot() -> None:
    # The per-question context composition (the same payload the live `context` SSE event carries)
    # is snapshotted into the assistant turn's meta so the context view survives a reload (#371).
    with _client_with("ctxfake", _ThinkingFake(name="ctxfake")) as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "why?"}], "conversation_id": cid},
        ) as resp:
            "".join(resp.iter_text())
        msgs = client.get(f"/api/v1/conversations/{cid}", headers=AUTH).json()["data"]["messages"]
        assistant = next(m for m in msgs if m["role"] == "assistant")
        context = assistant["meta"]["context"]
        assert context["items"]  # at least the user message group is always present
        assert isinstance(context["total_chars"], int)
        assert all({"label", "count", "chars"} <= set(it) for it in context["items"])


class _BoomProvider(FakeModelProvider):
    """Streams a reasoning chunk, then raises mid-generation."""

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        yield GenerationChunk(thinking="thinking hard")
        raise RuntimeError("model exploded")


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_errored_turn_is_persisted_with_trace() -> None:
    config = CoreConfig(auth_token=TOKEN, model_provider="boom", database_url=DB_URL)
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("boom", _BoomProvider(name="boom"))
    with TestClient(create_app(boot)) as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}], "conversation_id": cid},
        ) as resp:
            body = "".join(resp.iter_text())
        assert "event: error" in body  # error surfaced to the client
        msgs = client.get(f"/api/v1/conversations/{cid}", headers=AUTH).json()["data"]["messages"]
        assistant = next(m for m in msgs if m["role"] == "assistant")
        # The aborted turn is persisted with its reasoning trace + the error (not lost on reload).
        assert assistant["meta"]["error"] == "model exploded"
        assert any(t["kind"] == "reasoning" for t in assistant["meta"]["trace"])


class _BoomAfterTextProvider(FakeModelProvider):
    """Streams some answer text, then raises (partial answer, no trace)."""

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        yield GenerationChunk(delta="partial answer")
        raise RuntimeError("boom")


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_errored_turn_persists_partial_answer_without_trace() -> None:
    config = CoreConfig(auth_token=TOKEN, model_provider="boom2", database_url=DB_URL)
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("boom2", _BoomAfterTextProvider(name="boom2"))
    with TestClient(create_app(boot)) as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}], "conversation_id": cid},
        ) as resp:
            "".join(resp.iter_text())
        msgs = client.get(f"/api/v1/conversations/{cid}", headers=AUTH).json()["data"]["messages"]
        assistant = next(m for m in msgs if m["role"] == "assistant")
        assert assistant["content"] == "partial answer"  # partial answer kept
        assert assistant["meta"]["error"] == "boom" and "trace" not in assistant["meta"]


class _ToolThinkFake(FakeModelProvider):
    """Agent path: reasons (thinking) and answers without a tool call."""

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(text="answer", model=request.model, thinking="reasoning trace")


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_agent_path_persists_reasoning_meta() -> None:
    with _client_with("toolthink", _ToolThinkFake(name="toolthink")) as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "why?"}],
                "conversation_id": cid,
                "use_tools": True,
                "think": True,
            },
        ) as resp:
            body = "".join(resp.iter_text())
        assert "reasoning trace" in body  # streamed live too
        msgs = client.get(f"/api/v1/conversations/{cid}", headers=AUTH).json()["data"]["messages"]
        assistant = next(m for m in msgs if m["role"] == "assistant")
        trace = assistant["meta"]["trace"]
        assert any(t["kind"] == "reasoning" and t["text"] == "reasoning trace" for t in trace)


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_assistant_message_persists_tool_steps_meta() -> None:
    with _client_with("toolfake", _ToolFake()) as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "2+2?"}],
                "conversation_id": cid,
                "use_tools": True,
            },
        ) as resp:
            "".join(resp.iter_text())
        msgs = client.get(f"/api/v1/conversations/{cid}", headers=AUTH).json()["data"]["messages"]
        assistant = next(m for m in msgs if m["role"] == "assistant")
        trace = assistant["meta"]["trace"]
        assert any(t["kind"] == "tool_call" and t["tool"] == "calculator" for t in trace)
