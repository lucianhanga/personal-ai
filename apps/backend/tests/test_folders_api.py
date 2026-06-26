"""/api/v1/folders HTTP API (Documents v2 P1, #456): register/list/detail/delete/resync/pause +
the events SSE. DB-gated TestClient; a LOOPBACK fake embedder (passes the fail-closed guard) sized
to the pgvector column, so the real ingest pipeline runs with no Ollama."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Sequence as Seq
from typing import Any

import pytest
from fastapi.testclient import TestClient

from personalai_backend import create_app
from personalai_backend.composition import Bootstrap, bootstrap
from personalai_contracts.ports import EmbeddingResult
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig
from personalai_storage_postgres import VECTOR_DIM, create_pool

TOKEN = "test-secret-token"
DB_URL = os.environ.get(
    "PERSONALAI_DATABASE_URL", "postgresql://personalai@127.0.0.1:5432/personalai"
)
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class _LocalEmbed1024(FakeModelProvider):
    """Loopback embedder (passes assert_local_provider) sized to the pgvector column."""

    _host = "127.0.0.1"

    async def embed(self, texts: Seq[str], model: str) -> EmbeddingResult:
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


pytestmark = pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")


def _boot() -> Bootstrap:
    config = CoreConfig(
        auth_token=TOKEN,
        model_provider="fakeembed",
        embed_provider="fakeembed",
        database_url=DB_URL,
    )
    boot = bootstrap(config=config)
    boot.registries.model_providers.register("fakeembed", _LocalEmbed1024(name="fakeembed"))
    return boot


def _wait_synced(
    client: TestClient, source_id: str, *, files: int, tries: int = 80
) -> dict[str, Any]:
    """Poll the source until its initial background sync settles (idle + all files synced)."""
    body: dict[str, Any] = {}
    for _ in range(tries):
        body = client.get(f"/api/v1/folders/{source_id}", headers=AUTH).json()["data"]
        counts = body["source"]["counts"]
        if body["source"]["status"] == "idle" and counts.get("synced", 0) >= files:
            return body
        time.sleep(0.05)
    raise AssertionError(f"folder {source_id} did not sync: {body['source']}")


def test_register_indexes_then_list_detail_delete_purges(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # Unique content per run so the content-hash document id is unique -> the purge assertion is not
    # confounded by a doc the same content left referenced from a prior run (content-hash dedup).
    uniq = uuid.uuid4().hex
    (tmp_path / "a.txt").write_text(f"Lisbon is the capital of Portugal. {uniq} " * 5)
    (tmp_path / "b.txt").write_text(f"Bucharest is the capital of Romania. {uniq} " * 5)
    with TestClient(create_app(_boot())) as client:
        # Register -> 200, initial sync kicked in the background.
        reg = client.post(
            "/api/v1/folders", headers=AUTH, json={"path": str(tmp_path), "label": "Docs"}
        )
        assert reg.status_code == 200, reg.text
        src = reg.json()["data"]
        assert src["label"] == "Docs" and src["root_path"] == str(tmp_path.resolve())
        sid = src["id"]

        body = _wait_synced(client, sid, files=2)
        assert body["source"]["counts"]["synced"] == 2
        rels = {f["rel_path"]: f for f in body["files"]}
        assert set(rels) == {"a.txt", "b.txt"}
        assert all(f["status"] == "synced" and f["document_id"] for f in rels.values())

        # Folder-synced docs do NOT appear in the "Individual uploads" list (#451) -- they live in
        # the folder tree above, not the manual-uploads list.
        files_now = client.get("/api/v1/files", headers=AUTH).json()["data"]["files"]
        doc_ids = {rels["a.txt"]["document_id"], rels["b.txt"]["document_id"]}
        assert not (doc_ids & {f["id"] for f in files_now})

        # List shows the source + counts.
        listing = client.get("/api/v1/folders", headers=AUTH).json()["data"]["folders"]
        assert any(s["id"] == sid and s["counts"]["synced"] == 2 for s in listing)

        # Detail status-filter: only synced rows.
        only_synced = client.get(
            f"/api/v1/folders/{sid}", headers=AUTH, params={"status": "synced"}
        ).json()["data"]["files"]
        assert len(only_synced) == 2

        # Delete -> purge: the source is gone AND its docs leave the global corpus.
        d = client.delete(f"/api/v1/folders/{sid}", headers=AUTH)
        assert d.status_code == 200 and d.json()["data"]["purged_documents"] == 2
        assert client.get(f"/api/v1/folders/{sid}", headers=AUTH).status_code == 404
        after = {f["id"] for f in client.get("/api/v1/files", headers=AUTH).json()["data"]["files"]}
        assert not (doc_ids & after)


def test_reextract_reruns_ner_over_synced_files(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # #464: a dedicated NER re-extraction pass (the normal sync skips content-hash-deduped docs, so
    # it never re-extracts). Per-source + all-sources endpoints schedule a background re-parse + NER
    # over the already-synced files; a missing source 404s.
    (tmp_path / "a.txt").write_text(f"Acme Corp invoiced Bob. {uuid.uuid4().hex}")
    with TestClient(create_app(_boot())) as client:
        sid = client.post(
            "/api/v1/folders", headers=AUTH, json={"path": str(tmp_path), "label": "R"}
        ).json()["data"]["id"]
        _wait_synced(client, sid, files=1)

        one = client.post(f"/api/v1/folders/{sid}/reextract", headers=AUTH)
        assert one.status_code == 200 and one.json()["data"]["status"] == "reextracting"

        every = client.post("/api/v1/folders/reextract", headers=AUTH)
        assert every.status_code == 200 and every.json()["data"]["sources"] >= 1

        missing = client.post(
            "/api/v1/folders/00000000-0000-0000-0000-000000000000/reextract", headers=AUTH
        )
        assert missing.status_code == 404


def test_resync_and_pause_resume(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "x.txt").write_text("content")
    with TestClient(create_app(_boot())) as client:
        sid = client.post(
            "/api/v1/folders", headers=AUTH, json={"path": str(tmp_path), "label": "X"}
        ).json()["data"]["id"]
        _wait_synced(client, sid, files=1)

        # Pause/resume while idle (avoids racing an in-flight scan's finish_scan).
        paused = client.post(f"/api/v1/folders/{sid}/pause", headers=AUTH).json()["data"]
        assert paused["enabled"] is False and paused["status"] == "disabled"
        # Resync is refused while paused.
        blocked = client.post(f"/api/v1/folders/{sid}/resync", headers=AUTH).json()
        assert blocked["ok"] is False and blocked["error"]["code"] == "E_FOLDER_PAUSED"

        resumed = client.post(f"/api/v1/folders/{sid}/resume", headers=AUTH).json()["data"]
        assert resumed["enabled"] is True and resumed["status"] == "idle"

        # Resync is accepted once resumed.
        assert client.post(f"/api/v1/folders/{sid}/resync", headers=AUTH).status_code == 200
        _wait_synced(client, sid, files=1)


def test_register_errors_and_404(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with TestClient(create_app(_boot())) as client:
        missing = client.post(
            "/api/v1/folders", headers=AUTH, json={"path": str(tmp_path / "nope")}
        ).json()
        assert missing["ok"] is False and missing["error"]["code"] == "E_FOLDER_NOT_FOUND"

        f = tmp_path / "file.txt"
        f.write_text("x")
        not_dir = client.post("/api/v1/folders", headers=AUTH, json={"path": str(f)}).json()
        assert not_dir["error"]["code"] == "E_FOLDER_NOT_A_DIR"

        client.post("/api/v1/folders", headers=AUTH, json={"path": str(tmp_path), "label": "D"})
        dup = client.post("/api/v1/folders", headers=AUTH, json={"path": str(tmp_path)}).json()
        assert dup["error"]["code"] == "E_FOLDER_EXISTS"

        assert client.get("/api/v1/folders/does-not-exist", headers=AUTH).status_code == 404
        assert client.delete("/api/v1/folders/does-not-exist", headers=AUTH).status_code == 404


def test_events_sse_streams_progress_and_terminates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "doc.txt").write_text("hello")
    with TestClient(create_app(_boot())) as client:
        sid = client.post(
            "/api/v1/folders", headers=AUTH, json={"path": str(tmp_path), "label": "E"}
        ).json()["data"]["id"]
        _wait_synced(client, sid, files=1)
        with client.stream("GET", f"/api/v1/folders/{sid}/events", headers=AUTH) as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())
        assert "event: progress" in body
        assert "event: done" in body
