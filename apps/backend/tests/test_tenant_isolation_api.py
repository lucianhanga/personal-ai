"""P2: end-to-end tenant isolation through the HTTP API (two users -> separate data).

The headline multi-tenant test: it proves that data created by one logged-in user is invisible to
another. DB-gated. Uses hosted mode (real login) over https so Secure cookies round-trip.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from personalai_backend.app import create_app
from personalai_backend.composition import bootstrap
from personalai_backend.tenant_querier import TenantContextError, TenantQuerier
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig
from personalai_storage_postgres import PgConversationStore, create_pool

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


def _signup_login(client: TestClient, email: str) -> None:
    client.post("/api/v1/auth/signup", json={"email": email, "password": "pw"})
    assert (
        client.post("/api/v1/auth/login", json={"email": email, "password": "pw"}).status_code
        == 200
    )


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("pai_csrf") or ""}


def test_two_users_have_separate_conversations() -> None:
    app = create_app(bootstrap(config=CoreConfig(app_mode="hosted")))
    with TestClient(app, base_url="https://testserver") as alice:
        _signup_login(alice, f"alice-{uuid.uuid4().hex[:8]}@example.com")
        made = alice.post(
            "/api/v1/conversations", json={"title": "Alice secret"}, headers=_csrf(alice)
        )
        assert made.status_code == 200
        alice_titles = [
            c["title"] for c in alice.get("/api/v1/conversations").json()["data"]["conversations"]
        ]
        assert "Alice secret" in alice_titles

    with TestClient(app, base_url="https://testserver") as bob:
        _signup_login(bob, f"bob-{uuid.uuid4().hex[:8]}@example.com")
        bob_titles = [
            c["title"] for c in bob.get("/api/v1/conversations").json()["data"]["conversations"]
        ]
        assert "Alice secret" not in bob_titles  # Bob cannot see Alice's conversation


def test_chat_turn_is_tenant_isolated_on_the_stream_path() -> None:
    # The SSE chat path persists per-tenant: a turn run + persisted by one user is invisible to
    # another (audit A5 — the streaming path was previously untested for isolation).
    boot = bootstrap(config=CoreConfig(app_mode="hosted"))
    boot.registries.model_providers.register("fake", FakeModelProvider(name="fake"), overwrite=True)
    app = create_app(boot)

    cid = ""
    with TestClient(app, base_url="https://testserver") as alice:
        _signup_login(alice, f"alice-{uuid.uuid4().hex[:8]}@example.com")
        cid = alice.post(
            "/api/v1/conversations", json={"title": "A chat"}, headers=_csrf(alice)
        ).json()["data"]["id"]
        with alice.stream(
            "POST",
            "/api/v1/chat",
            headers=_csrf(alice),
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "provider": "fake",
                "conversation_id": cid,
            },
        ) as resp:
            assert resp.status_code == 200
            "".join(resp.iter_text())
        alice_msgs = alice.get(f"/api/v1/conversations/{cid}").json()["data"]["messages"]
        assert len(alice_msgs) >= 1  # the turn persisted to Alice's conversation

    with TestClient(app, base_url="https://testserver") as bob:
        _signup_login(bob, f"bob-{uuid.uuid4().hex[:8]}@example.com")
        ids = [c["id"] for c in bob.get("/api/v1/conversations").json()["data"]["conversations"]]
        assert cid not in ids  # Bob cannot list Alice's conversation
        assert bob.get(f"/api/v1/conversations/{cid}").status_code == 404  # nor fetch its messages


def test_querier_fails_closed_without_context() -> None:
    # A store query with no SecurityContext in scope must raise, never use a default tenant.
    async def _run() -> None:
        pool = await create_pool(DB_URL)
        try:
            store = PgConversationStore(TenantQuerier(pool))
            with pytest.raises(TenantContextError):
                await store.list()
        finally:
            await pool.close()

    asyncio.run(_run())
