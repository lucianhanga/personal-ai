"""Conversation endpoints + chat persistence. CRUD/persistence need Postgres (skipped otherwise);
the 503 path needs no DB."""

from __future__ import annotations

import asyncio
import os

import pytest
from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import bootstrap
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig
from personalai_storage_postgres import create_pool

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


def _client(database_url: str = DB_URL) -> TestClient:
    config = CoreConfig(auth_token=TOKEN, model_provider="fake", database_url=database_url)
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
        roles = [
            m["role"]
            for m in client.get(f"/api/conversations/{cid}", headers=AUTH).json()["data"]["messages"]
        ]
        assert "user" not in roles  # no user turn was present, so none was persisted


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_chat_unknown_conversation_404() -> None:
    with _client() as client:
        resp = client.post(
            "/api/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}], "conversation_id": "nope"},
        )
        assert resp.status_code == 404
