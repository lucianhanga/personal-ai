"""File ingestion endpoints. The 503 path needs no DB; the happy path needs Postgres (skipped
otherwise). Embeddings use a local fake sized to the pgvector column (1024), so no Ollama needed."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import Bootstrap, bootstrap
from personalai_contracts.ports import EmbeddingResult
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig
from personalai_storage_postgres import VECTOR_DIM, apply_migrations, create_pool

TOKEN = "test-secret-token"
DB_URL = os.environ.get(
    "PERSONALAI_DATABASE_URL", "postgresql://personalai@127.0.0.1:5432/personalai"
)
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class _Embed1024(FakeModelProvider):
    """Fake provider whose embeddings match the pgvector column dimension."""

    async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[0.0] * (VECTOR_DIM - 1) + [1.0] for _ in texts],
            model=model,
            dimensions=VECTOR_DIM,
        )


def _db_available() -> bool:
    async def _check() -> bool:
        try:
            pool = await create_pool(DB_URL)
        except Exception:
            return False
        await pool.close()
        return True

    return asyncio.run(_check())


def test_files_unavailable_without_storage_returns_503() -> None:
    # Unreachable DB -> lifespan storage startup fails -> file routes are 503 (fail-closed).
    bad_url = "postgresql://personalai@127.0.0.1:59999/x"
    config = CoreConfig(auth_token=TOKEN, database_url=bad_url)
    with TestClient(create_app(bootstrap(config=config))) as client:
        assert client.get("/api/v1/files", headers=AUTH).status_code == 503


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_upload_list_delete_roundtrip() -> None:
    config = CoreConfig(auth_token=TOKEN, embed_provider="fakeembed", database_url=DB_URL)
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("fakeembed", _Embed1024(name="fakeembed"))
    with TestClient(create_app(boot)) as client:
        up = client.post(
            "/api/v1/files",
            headers=AUTH,
            files={"file": ("notes.txt", b"hello world. " * 50, "text/plain")},
        )
        assert up.status_code == 200, up.text
        body = up.json()
        assert body["ok"] is True
        doc_id = body["data"]["id"]
        assert body["data"]["chunk_count"] > 0

        listed = client.get("/api/v1/files", headers=AUTH).json()["data"]["files"]
        assert any(f["id"] == doc_id for f in listed)

        assert client.delete(f"/api/v1/files/{doc_id}", headers=AUTH).status_code == 200
        after = client.get("/api/v1/files", headers=AUTH).json()["data"]["files"]
        assert all(f["id"] != doc_id for f in after)


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_unsupported_file_type_is_structured_error() -> None:
    config = CoreConfig(auth_token=TOKEN, embed_provider="fakeembed", database_url=DB_URL)
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("fakeembed", _Embed1024(name="fakeembed"))
    with TestClient(create_app(boot)) as client:
        resp = client.post(
            "/api/v1/files", headers=AUTH, files={"file": ("photo.heic", b"\x00\x01", "image/heic")}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "E_UNSUPPORTED_FILE"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_delete_unknown_document_404() -> None:
    config = CoreConfig(auth_token=TOKEN, embed_provider="fakeembed", database_url=DB_URL)
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("fakeembed", _Embed1024(name="fakeembed"))
    with TestClient(create_app(boot)) as client:
        assert client.delete("/api/v1/files/does-not-exist", headers=AUTH).status_code == 404


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_chat_with_rag_emits_citations() -> None:
    config = CoreConfig(
        auth_token=TOKEN,
        model_provider="fakeembed",
        embed_provider="fakeembed",
        database_url=DB_URL,
    )
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("fakeembed", _Embed1024(name="fakeembed"))
    with TestClient(create_app(boot)) as client:
        up = client.post(
            "/api/v1/files",
            headers=AUTH,
            files={"file": ("geo.txt", b"Lisbon is the capital of Portugal. " * 10, "text/plain")},
        )
        assert up.json()["data"]["chunk_count"] > 0
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "What is the capital?"}],
                "use_rag": True,
            },
        ) as resp:
            body = "".join(resp.iter_text())
        assert "event: citations" in body
        assert "source_id" in body


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_chat_with_rag_no_matches_emits_no_citations() -> None:
    async def _truncate() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            await pool.execute("TRUNCATE vectors")
        finally:
            await pool.close()

    asyncio.run(_truncate())
    config = CoreConfig(
        auth_token=TOKEN,
        model_provider="fakeembed",
        embed_provider="fakeembed",
        database_url=DB_URL,
    )
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("fakeembed", _Embed1024(name="fakeembed"))
    with TestClient(create_app(boot)) as client:
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "anything?"}], "use_rag": True},
        ) as resp:
            body = "".join(resp.iter_text())
        assert "event: citations" not in body


def test_chat_with_rag_without_storage_streams_normally() -> None:
    # use_rag requested but no DB -> retrieval is skipped (no citations), chat still works.
    config = CoreConfig(
        auth_token=TOKEN,
        model_provider="fakeembed",
        database_url="postgresql://personalai@127.0.0.1:59999/x",
    )
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("fakeembed", _Embed1024(name="fakeembed"))
    with TestClient(create_app(boot)) as client:
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}], "use_rag": True},
        ) as resp:
            body = "".join(resp.iter_text())
        assert "event: citations" not in body


# --- RAG-pipeline "context prelude" trace events (#437) -------------------------------------------
# These exercise the indexing/retrieval items emitted into the trace SSE + the persisted
# meta["trace"] through the real /api/v1/chat call (Postgres-backed vector store). The pure builders
# are unit-tested in test_rag_prelude.py; here we prove emit + persist + ordering end to end.


def _rag_boot() -> Bootstrap:
    config = CoreConfig(
        auth_token=TOKEN,
        model_provider="fakeembed",
        embed_provider="fakeembed",
        database_url=DB_URL,
    )
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("fakeembed", _Embed1024(name="fakeembed"))
    return boot


def _assistant_trace(client: TestClient, cid: str) -> list[dict[str, Any]]:
    msgs = client.get(f"/api/v1/conversations/{cid}", headers=AUTH).json()["data"]["messages"]
    assistant = next(m for m in reversed(msgs) if m["role"] == "assistant")
    return assistant.get("meta", {}).get("trace", []) or []


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_retrieval_event_emitted_and_persisted_and_ordered_first() -> None:
    # A RAG turn in a conversation emits a `retrieval` event live AND persists it as the FIRST trace
    # item (the prelude is prepended ahead of any agent step). Scope is "union" with a conversation.
    with TestClient(create_app(_rag_boot())) as client:
        client.post(
            "/api/v1/files",
            headers=AUTH,
            files={"file": ("geo.txt", b"Lisbon is the capital of Portugal. " * 10, "text/plain")},
        )
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "What is the capital?"}],
                "use_rag": True,
                "conversation_id": cid,
            },
        ) as resp:
            body = "".join(resp.iter_text())
        assert "event: retrieval" in body  # streamed live before the agent loop

        trace = _assistant_trace(client, cid)
        rag = [t for t in trace if t["kind"] in ("indexing", "retrieval", "ner")]
        assert rag, "the prelude must persist into meta['trace']"
        assert trace[0]["kind"] == "retrieval", "the prelude is prepended ahead of agent steps"
        ret = trace[0]
        assert ret["hits"] >= 1
        assert ret["scope"] == "union"
        assert ret["citations"] and {"source", "score"} <= set(ret["citations"][0].keys())
        # No agent (reasoning/tool/plan) step leaked ahead of the prelude.
        first_agent = next(
            (i for i, t in enumerate(trace) if t["kind"] not in ("indexing", "retrieval", "ner")),
            len(trace),
        )
        last_prelude = max(
            i for i, t in enumerate(trace) if t["kind"] in ("indexing", "retrieval", "ner")
        )
        assert last_prelude < first_agent, "prelude items come before agent steps"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_indexing_event_emitted_for_large_attachment_then_retrieval() -> None:
    # A large doc sent at-send (documents_full) is ingested -> one `indexing` item, then the
    # `retrieval` item, in that order, both live and persisted.
    with TestClient(create_app(_rag_boot())) as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        big = "Wexford is the teal octopus mascot in the attached report. " * 40
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": "Who is the mascot?",
                        "documents_full": [{"name": "report.txt", "text": big}],
                    }
                ],
                "use_rag": True,
                "conversation_id": cid,
            },
        ) as resp:
            body = "".join(resp.iter_text())
        assert "event: indexing" in body
        assert "event: retrieval" in body

        trace = _assistant_trace(client, cid)
        kinds = [t["kind"] for t in trace]
        assert "indexing" in kinds and "retrieval" in kinds
        assert kinds.index("indexing") < kinds.index("retrieval"), "indexing precedes retrieval"
        idx = next(t for t in trace if t["kind"] == "indexing")
        assert idx["ref"] == "report.txt"
        assert idx["chunks"] >= 1
        assert "status" not in idx  # success carries no error


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_zero_hit_retrieval_is_emitted_as_signal() -> None:
    # RAG ran but matched nothing -> a deliberate `retrieval` item with hits:0 and empty citations
    # (honest "searched, found nothing"), NOT suppressed.
    async def _truncate() -> None:
        pool = await create_pool(DB_URL)
        try:
            await apply_migrations(pool)
            await pool.execute("TRUNCATE vectors")
        finally:
            await pool.close()

    asyncio.run(_truncate())
    with TestClient(create_app(_rag_boot())) as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "anything?"}],
                "use_rag": True,
                "conversation_id": cid,
            },
        ) as resp:
            body = "".join(resp.iter_text())
        assert "event: retrieval" in body
        assert "event: citations" not in body  # 0-hit -> no answer-bubble citations frame

        trace = _assistant_trace(client, cid)
        ret = next(t for t in trace if t["kind"] == "retrieval")
        assert ret["hits"] == 0
        assert ret["citations"] == []


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_rag_off_emits_no_prelude_items() -> None:
    # use_rag false -> no indexing/retrieval events, and the persisted trace has none of the new
    # kinds (a legacy/non-RAG turn renders exactly as before).
    with TestClient(create_app(_rag_boot())) as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "use_rag": False,
                "conversation_id": cid,
            },
        ) as resp:
            body = "".join(resp.iter_text())
        assert "event: indexing" not in body
        assert "event: retrieval" not in body

        trace = _assistant_trace(client, cid)
        assert all(t["kind"] not in ("indexing", "retrieval", "ner") for t in trace)


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_eager_ingest_attachment_endpoint() -> None:
    # Tier-2 ingest-at-attach (#420): POST a large attachment into a conversation's scope BEFORE any
    # message; it indexes now, is idempotent on re-post, and is then retrievable (citations).
    with TestClient(create_app(_rag_boot())) as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        big = "Wexford is the teal octopus mascot of the attached report. " * 40
        first = client.post(
            f"/api/v1/conversations/{cid}/documents",
            headers=AUTH,
            json={"name": "report.pdf", "text": big},
        )
        assert first.status_code == 200, first.text
        data = first.json()["data"]
        assert first.json()["ok"] is True
        assert data["chunk_count"] > 0
        assert data["already_indexed"] is False

        # Idempotent: the same content re-posted skips re-embedding (no duplicate vectors).
        again = client.post(
            f"/api/v1/conversations/{cid}/documents",
            headers=AUTH,
            json={"name": "report.pdf", "text": big},
        )
        assert again.json()["data"]["already_indexed"] is True

        # The eagerly-indexed doc is now searchable in THIS conversation (union retrieval -> cites).
        with client.stream(
            "POST",
            "/api/v1/chat",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "Who is Wexford?"}],
                "use_rag": True,
                "conversation_id": cid,
            },
        ) as resp:
            body = "".join(resp.iter_text())
        assert "event: citations" in body


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_eager_ingest_unknown_conversation_404() -> None:
    with TestClient(create_app(_rag_boot())) as client:
        resp = client.post(
            "/api/v1/conversations/00000000-0000-0000-0000-000000000000/documents",
            headers=AUTH,
            json={"name": "x.pdf", "text": "hello"},
        )
        assert resp.status_code == 404


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_eager_ingest_empty_text_is_structured_error() -> None:
    with TestClient(create_app(_rag_boot())) as client:
        cid = client.post("/api/v1/conversations", headers=AUTH, json={}).json()["data"]["id"]
        resp = client.post(
            f"/api/v1/conversations/{cid}/documents",
            headers=AUTH,
            json={"name": "blank.pdf", "text": "   "},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is False
        assert resp.json()["error"]["code"] == "E_EMPTY_DOC"
