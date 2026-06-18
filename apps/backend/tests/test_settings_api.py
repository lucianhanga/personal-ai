"""#289: per-tenant preference settings over the HTTP API (round-trip, isolation, validation).

DB-gated. Uses hosted mode (real login) over https so Secure cookies round-trip, matching the other
tenant-isolation API tests.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from personalai_backend.app import create_app
from personalai_backend.composition import bootstrap
from personalai_core import CoreConfig
from personalai_storage_postgres import create_pool

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


def test_settings_get_defaults_then_round_trip() -> None:
    app = create_app(bootstrap(config=CoreConfig(app_mode="hosted")))
    with TestClient(app, base_url="https://testserver") as user:
        _signup_login(user, f"u-{uuid.uuid4().hex[:8]}@example.com")

        # No saved settings yet: every override is null and `defaults` echoes the boot config.
        body = user.get("/api/v1/settings").json()["data"]
        assert body["settings"]["default_model"] is None
        assert body["defaults"]["default_model"] == CoreConfig().default_model
        assert body["defaults"]["agent_graph_enabled"] is False

        saved = user.put(
            "/api/v1/settings",
            headers=_csrf(user),
            json={"default_model": "qwen3:14b", "agent_graph_enabled": True},
        )
        assert saved.status_code == 200
        assert saved.json()["data"]["settings"]["default_model"] == "qwen3:14b"

        reloaded = user.get("/api/v1/settings").json()["data"]["settings"]
        assert reloaded["default_model"] == "qwen3:14b"
        assert reloaded["agent_graph_enabled"] is True


def test_settings_are_isolated_between_tenants() -> None:
    app = create_app(bootstrap(config=CoreConfig(app_mode="hosted")))
    with TestClient(app, base_url="https://testserver") as alice:
        _signup_login(alice, f"alice-{uuid.uuid4().hex[:8]}@example.com")
        alice.put(
            "/api/v1/settings", headers=_csrf(alice), json={"default_model": "alice-model"}
        )

    with TestClient(app, base_url="https://testserver") as bob:
        _signup_login(bob, f"bob-{uuid.uuid4().hex[:8]}@example.com")
        # Bob never saved anything: he sees the default, NOT Alice's override (RLS).
        assert bob.get("/api/v1/settings").json()["data"]["settings"]["default_model"] is None


def test_settings_reject_out_of_range_values() -> None:
    app = create_app(bootstrap(config=CoreConfig(app_mode="hosted")))
    with TestClient(app, base_url="https://testserver") as user:
        _signup_login(user, f"u-{uuid.uuid4().hex[:8]}@example.com")
        # agent_max_iterations is bounded 1..50; 999 must fail validation (422), not persist.
        bad = user.put(
            "/api/v1/settings", headers=_csrf(user), json={"agent_max_iterations": 999}
        )
        assert bad.status_code == 422
        # Unknown/secret fields are rejected (extra="forbid") -- the API never accepts secrets.
        secret = user.put(
            "/api/v1/settings", headers=_csrf(user), json={"openai_api_key": "sk-leak"}
        )
        assert secret.status_code == 422
