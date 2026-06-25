"""#441 message management + #412 cancel through the HTTP API (DB-gated).

Covers: get_conversation exposes a stable per-message id; the truncate-from-turn endpoint deletes
id>=N (Delete = truncate-only); Edit = truncate then re-run via /chat; truncate authz (404 on a
foreign/garbage id, cross-tenant denied); and the gated-run /cancel authz + checkpoint cleanup.
Hosted mode (real login) over https so Secure cookies round-trip (per test_tenant_isolation_api).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator, Sequence

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from personalai_backend.app import create_app
from personalai_backend.composition import bootstrap
from personalai_contracts.ports import (
    EmbeddingResult,
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    ModelCapabilities,
    ModelDescriptor,
)
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig
from personalai_storage_postgres import create_pool


class _CancelMidStreamProvider:
    """Streams an answer delta then raises CancelledError, simulating the client-disconnect that
    closes the SSE socket mid-stream (#412, path A) — so the route's persist-on-cancel runs."""

    name = "cancelly"

    async def capabilities(self, model: str) -> ModelCapabilities:
        raise NotImplementedError

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        raise NotImplementedError

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        yield GenerationChunk(delta="The capital of France is Par")
        raise asyncio.CancelledError  # the consumer (client) went away

    async def list_models(self) -> Sequence[ModelDescriptor]:
        return []

    async def embed(self, texts: Sequence[str], model: str) -> EmbeddingResult:
        raise NotImplementedError


DB_URL = os.environ.get(
    "PERSONALAI_DATABASE_URL", "postgresql://personalai@127.0.0.1:5432/personalai"
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


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="Postgres not reachable (run `make db`)"
)


_TEST_PW = "pw"  # pragma: allowlist secret  (throwaway password for the test signup/login)


def _signup_login(client: TestClient, email: str) -> None:
    client.post("/api/v1/auth/signup", json={"email": email, "password": _TEST_PW})
    assert (
        client.post("/api/v1/auth/login", json={"email": email, "password": _TEST_PW}).status_code
        == 200
    )


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("pai_csrf") or ""}


def _run_id_from_sse(body: str) -> str | None:
    for frame in body.split("\n\n"):
        if "event: approval_request" in frame:
            data = next(line for line in frame.splitlines() if line.startswith("data: "))
            return str(json.loads(data[len("data: ") :])["run_id"])
    return None


def _fake_app(**cfg: object) -> FastAPI:
    boot = bootstrap(config=CoreConfig(app_mode="hosted", **cfg))  # type: ignore[arg-type]
    boot.registries.model_providers.register("fake", FakeModelProvider(name="fake"), overwrite=True)
    return create_app(boot)


def _send_turn(client: TestClient, cid: str, content: str) -> str:
    with client.stream(
        "POST",
        "/api/v1/chat",
        headers=_csrf(client),
        json={
            "messages": [{"role": "user", "content": content}],
            "provider": "fake",
            "conversation_id": cid,
        },
    ) as resp:
        assert resp.status_code == 200
        return "".join(resp.iter_text())


def test_get_conversation_exposes_message_ids() -> None:
    app = _fake_app()
    with TestClient(app, base_url="https://testserver") as alice:
        _signup_login(alice, f"alice-{uuid.uuid4().hex[:8]}@example.com")
        cid = alice.post(
            "/api/v1/conversations", json={"title": "ids"}, headers=_csrf(alice)
        ).json()["data"]["id"]
        _send_turn(alice, cid, "hello")
        msgs = alice.get(f"/api/v1/conversations/{cid}").json()["data"]["messages"]
        assert len(msgs) >= 2  # user + assistant
        # Every message carries a stable integer id, strictly increasing (the truncate cursor).
        ids = [m["id"] for m in msgs]
        assert all(isinstance(i, int) for i in ids)
        assert ids == sorted(ids)


def test_truncate_deletes_from_turn_onward() -> None:
    app = _fake_app()
    with TestClient(app, base_url="https://testserver") as alice:
        _signup_login(alice, f"alice-{uuid.uuid4().hex[:8]}@example.com")
        cid = alice.post(
            "/api/v1/conversations", json={"title": "trunc"}, headers=_csrf(alice)
        ).json()["data"]["id"]
        _send_turn(alice, cid, "q1")
        _send_turn(alice, cid, "q2")
        msgs = alice.get(f"/api/v1/conversations/{cid}").json()["data"]["messages"]
        # Find the second user turn (q2) and truncate from it.
        q2 = next(m for m in msgs if m["role"] == "user" and m["content"] == "q2")
        res = alice.post(
            f"/api/v1/conversations/{cid}/truncate",
            json={"from_message_id": q2["id"]},
            headers=_csrf(alice),
        )
        assert res.status_code == 200
        assert res.json()["data"]["deleted_count"] >= 1
        remaining = alice.get(f"/api/v1/conversations/{cid}").json()["data"]["messages"]
        # q1 + its answer survive; q2 + its answer are gone.
        contents = [m["content"] for m in remaining]
        assert "q1" in contents
        assert "q2" not in contents


def test_truncate_unknown_message_id_is_404() -> None:
    app = _fake_app()
    with TestClient(app, base_url="https://testserver") as alice:
        _signup_login(alice, f"alice-{uuid.uuid4().hex[:8]}@example.com")
        cid = alice.post("/api/v1/conversations", json={"title": "t"}, headers=_csrf(alice)).json()[
            "data"
        ]["id"]
        _send_turn(alice, cid, "q1")
        # A garbage id that isn't in this conversation -> 404, not a silent no-op.
        res = alice.post(
            f"/api/v1/conversations/{cid}/truncate",
            json={"from_message_id": 999_999_999},
            headers=_csrf(alice),
        )
        assert res.status_code == 404
        # The conversation is untouched.
        assert len(alice.get(f"/api/v1/conversations/{cid}").json()["data"]["messages"]) >= 2


def test_truncate_is_cross_tenant_denied() -> None:
    app = _fake_app()
    alice_email = f"alice-{uuid.uuid4().hex[:8]}@example.com"
    cid = ""
    msg_id = 0
    with TestClient(app, base_url="https://testserver") as alice:
        _signup_login(alice, alice_email)
        cid = alice.post("/api/v1/conversations", json={"title": "a"}, headers=_csrf(alice)).json()[
            "data"
        ]["id"]
        _send_turn(alice, cid, "q1")
        msgs = alice.get(f"/api/v1/conversations/{cid}").json()["data"]["messages"]
        msg_id = msgs[0]["id"]

    # Bob (different tenant) cannot truncate Alice's conversation -> 404 (RLS hides it entirely).
    with TestClient(app, base_url="https://testserver") as bob:
        _signup_login(bob, f"bob-{uuid.uuid4().hex[:8]}@example.com")
        denied = bob.post(
            f"/api/v1/conversations/{cid}/truncate",
            json={"from_message_id": msg_id},
            headers=_csrf(bob),
        )
        assert denied.status_code == 404

    # Alice's turn is intact.
    with TestClient(app, base_url="https://testserver") as alice2:
        _signup_login(alice2, alice_email)
        assert len(alice2.get(f"/api/v1/conversations/{cid}").json()["data"]["messages"]) >= 2


def test_edit_is_truncate_then_rerun() -> None:
    app = _fake_app()
    with TestClient(app, base_url="https://testserver") as alice:
        _signup_login(alice, f"alice-{uuid.uuid4().hex[:8]}@example.com")
        cid = alice.post(
            "/api/v1/conversations", json={"title": "edit"}, headers=_csrf(alice)
        ).json()["data"]["id"]
        _send_turn(alice, cid, "first question")
        msgs = alice.get(f"/api/v1/conversations/{cid}").json()["data"]["messages"]
        first_user = next(m for m in msgs if m["role"] == "user")

        # Edit = truncate from the user turn, then re-run with the edited text via /chat.
        assert (
            alice.post(
                f"/api/v1/conversations/{cid}/truncate",
                json={"from_message_id": first_user["id"]},
                headers=_csrf(alice),
            ).status_code
            == 200
        )
        assert alice.get(f"/api/v1/conversations/{cid}").json()["data"]["messages"] == []
        _send_turn(alice, cid, "edited question")
        after = alice.get(f"/api/v1/conversations/{cid}").json()["data"]["messages"]
        contents = [m["content"] for m in after]
        assert "edited question" in contents
        assert "first question" not in contents
        assert any(m["role"] == "assistant" for m in after)  # the re-run produced a new answer


def test_delete_is_truncate_only() -> None:
    app = _fake_app()
    with TestClient(app, base_url="https://testserver") as alice:
        _signup_login(alice, f"alice-{uuid.uuid4().hex[:8]}@example.com")
        cid = alice.post(
            "/api/v1/conversations", json={"title": "del"}, headers=_csrf(alice)
        ).json()["data"]["id"]
        _send_turn(alice, cid, "only question")
        msgs = alice.get(f"/api/v1/conversations/{cid}").json()["data"]["messages"]
        first_user = next(m for m in msgs if m["role"] == "user")
        alice.post(
            f"/api/v1/conversations/{cid}/truncate",
            json={"from_message_id": first_user["id"]},
            headers=_csrf(alice),
        )
        # Delete does NOT re-run: the conversation is now empty (no new assistant turn).
        assert alice.get(f"/api/v1/conversations/{cid}").json()["data"]["messages"] == []


def test_disconnect_persists_partial_with_stopped_marker() -> None:
    # #412 path A: a client disconnect mid-stream (here, a provider that raises CancelledError after
    # one delta) persists the partial answer with meta["stopped"] = {"by": "user"} — distinct from
    # the error path — so reopening the chat shows the kept partial, framed as a user stop.
    boot = bootstrap(config=CoreConfig(app_mode="hosted"))
    boot.registries.model_providers.register("cancelly", _CancelMidStreamProvider(), overwrite=True)
    app = create_app(boot)
    with TestClient(app, base_url="https://testserver") as alice:
        _signup_login(alice, f"alice-{uuid.uuid4().hex[:8]}@example.com")
        cid = alice.post(
            "/api/v1/conversations", json={"title": "stop"}, headers=_csrf(alice)
        ).json()["data"]["id"]
        # The stream is cancelled server-side; consuming it may raise — that is the disconnect.
        try:
            with alice.stream(
                "POST",
                "/api/v1/chat",
                headers=_csrf(alice),
                json={
                    "messages": [{"role": "user", "content": "capital of France?"}],
                    "provider": "cancelly",
                    "conversation_id": cid,
                },
            ) as resp:
                "".join(resp.iter_text())
        except Exception:
            pass  # a mid-stream cancel surfaces as a transport error — expected

        msgs = alice.get(f"/api/v1/conversations/{cid}").json()["data"]["messages"]
        assistant = [m for m in msgs if m["role"] == "assistant"]
        assert assistant, "the partial assistant turn should be persisted on cancel"
        last = assistant[-1]
        assert "Par" in last["content"]  # the kept partial answer
        assert (last["meta"] or {}).get("stopped", {}).get("by") == "user"
        # Memory extraction is gated on a successful answer, so a cancelled turn schedules none
        # (no assertion needed beyond it not raising) — the turn is marked stopped, not failed.
        assert "error" not in (last["meta"] or {})  # not the red error path


def test_cancel_clears_a_gated_run_and_is_authz_safe() -> None:
    # #412: a run suspended at the human gate can be cancelled by its owner -> the durable
    # checkpoint is deleted so a subsequent /resume 404s. Cross-tenant cancel -> 404 (RLS).
    app = _fake_app(agent_mode="multi", agent_human_gate=True)
    alice_email = f"alice-{uuid.uuid4().hex[:8]}@example.com"

    # 1) Alice starts a gated turn that suspends at the gate.
    with TestClient(app, base_url="https://testserver") as alice:
        _signup_login(alice, alice_email)
        cid = alice.post(
            "/api/v1/conversations", json={"title": "gated"}, headers=_csrf(alice)
        ).json()["data"]["id"]
        with alice.stream(
            "POST",
            "/api/v1/chat",
            headers=_csrf(alice),
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "provider": "fake",
                "use_tools": True,
                "conversation_id": cid,
            },
        ) as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())
    run_id = _run_id_from_sse(body)
    assert run_id is not None

    # 2) Bob cannot cancel Alice's run -> 404 (cross-tenant, RLS).
    with TestClient(app, base_url="https://testserver") as bob:
        _signup_login(bob, f"bob-{uuid.uuid4().hex[:8]}@example.com")
        assert bob.post(f"/api/v1/chat/{run_id}/cancel", headers=_csrf(bob)).status_code == 404

    # 3) Alice cancels her own run -> 200; the checkpoint is gone, so /resume now 404s. Idempotent.
    with TestClient(app, base_url="https://testserver") as alice2:
        _signup_login(alice2, alice_email)
        ok = alice2.post(f"/api/v1/chat/{run_id}/cancel", headers=_csrf(alice2))
        assert ok.status_code == 200 and ok.json()["data"]["cancelled"] is True
        gone = alice2.post(
            f"/api/v1/chat/{run_id}/resume",
            json={"decision": "approve", "conversation_id": ""},
            headers=_csrf(alice2),
        )
        assert gone.status_code == 404  # not resumable after cancel
        # Cancelling again is harmless (idempotent): the run is already gone -> 404.
        again = alice2.post(f"/api/v1/chat/{run_id}/cancel", headers=_csrf(alice2))
        assert again.status_code == 404
