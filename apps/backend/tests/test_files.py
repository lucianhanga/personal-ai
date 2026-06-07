"""File ingestion endpoints. The 503 path needs no DB; the happy path needs Postgres (skipped
otherwise). Embeddings use a local fake sized to the pgvector column (1024), so no Ollama needed."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence

import pytest
from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import bootstrap
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
        assert client.get("/api/files", headers=AUTH).status_code == 503


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_upload_list_delete_roundtrip() -> None:
    config = CoreConfig(auth_token=TOKEN, embed_provider="fakeembed", database_url=DB_URL)
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("fakeembed", _Embed1024(name="fakeembed"))
    with TestClient(create_app(boot)) as client:
        up = client.post(
            "/api/files",
            headers=AUTH,
            files={"file": ("notes.txt", b"hello world. " * 50, "text/plain")},
        )
        assert up.status_code == 200, up.text
        body = up.json()
        assert body["ok"] is True
        doc_id = body["data"]["id"]
        assert body["data"]["chunk_count"] > 0

        listed = client.get("/api/files", headers=AUTH).json()["data"]["files"]
        assert any(f["id"] == doc_id for f in listed)

        assert client.delete(f"/api/files/{doc_id}", headers=AUTH).status_code == 200
        after = client.get("/api/files", headers=AUTH).json()["data"]["files"]
        assert all(f["id"] != doc_id for f in after)


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable (run `make db`)")
def test_unsupported_file_type_is_structured_error() -> None:
    config = CoreConfig(auth_token=TOKEN, embed_provider="fakeembed", database_url=DB_URL)
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("fakeembed", _Embed1024(name="fakeembed"))
    with TestClient(create_app(boot)) as client:
        resp = client.post(
            "/api/files", headers=AUTH, files={"file": ("photo.heic", b"\x00\x01", "image/heic")}
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
        assert client.delete("/api/files/does-not-exist", headers=AUTH).status_code == 404


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
            "/api/files",
            headers=AUTH,
            files={"file": ("geo.txt", b"Lisbon is the capital of Portugal. " * 10, "text/plain")},
        )
        assert up.json()["data"]["chunk_count"] > 0
        with client.stream(
            "POST",
            "/api/chat",
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
            "/api/chat",
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
            "/api/chat",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}], "use_rag": True},
        ) as resp:
            body = "".join(resp.iter_text())
        assert "event: citations" not in body
