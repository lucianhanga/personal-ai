"""#290: multi-agent graph config over the HTTP API (roster, round-trip, isolation, validation).

DB-gated, hosted mode (real login over https) like the other tenant-isolation API tests.
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


def test_agent_config_roster_defaults_and_round_trip() -> None:
    app = create_app(bootstrap(config=CoreConfig(app_mode="hosted")))
    with TestClient(app, base_url="https://testserver") as user:
        _signup_login(user, f"u-{uuid.uuid4().hex[:8]}@example.com")

        body = user.get("/api/v1/agents/config").json()["data"]
        # Roster: planner/researcher/critic/verifier, only the researcher uses tools.
        roster = {a["name"]: a["uses_tools"] for a in body["agents"]}
        assert roster == {
            "planner": False,
            "researcher": True,
            "critic": False,
            "verifier": False,
        }
        assert set(body["defaults"]) == {"planner", "researcher", "critic", "verifier"}
        assert isinstance(body["available_tools"], list)
        assert body["config"]["agents"] == []  # nothing saved yet

        saved = user.put(
            "/api/v1/agents/config",
            headers=_csrf(user),
            json={
                "agents": [
                    {"name": "planner", "prompt": "Plan tersely."},
                    {"name": "researcher", "disabled_tools": ["http_fetch"]},
                ]
            },
        )
        assert saved.status_code == 200

        reloaded = user.get("/api/v1/agents/config").json()["data"]["config"]
        by_name = {a["name"]: a for a in reloaded["agents"]}
        assert by_name["planner"]["prompt"] == "Plan tersely."
        assert by_name["researcher"]["disabled_tools"] == ["http_fetch"]


def test_agent_config_rejects_unknown_agent() -> None:
    app = create_app(bootstrap(config=CoreConfig(app_mode="hosted")))
    with TestClient(app, base_url="https://testserver") as user:
        _signup_login(user, f"u-{uuid.uuid4().hex[:8]}@example.com")
        bad = user.put(
            "/api/v1/agents/config",
            headers=_csrf(user),
            json={"agents": [{"name": "wizard", "prompt": "do magic"}]},
        )
        assert bad.status_code == 400


def test_agent_config_is_isolated_between_tenants() -> None:
    app = create_app(bootstrap(config=CoreConfig(app_mode="hosted")))
    with TestClient(app, base_url="https://testserver") as alice:
        _signup_login(alice, f"alice-{uuid.uuid4().hex[:8]}@example.com")
        alice.put(
            "/api/v1/agents/config",
            headers=_csrf(alice),
            json={"agents": [{"name": "planner", "prompt": "alice-only"}]},
        )

    with TestClient(app, base_url="https://testserver") as bob:
        _signup_login(bob, f"bob-{uuid.uuid4().hex[:8]}@example.com")
        cfg = bob.get("/api/v1/agents/config").json()["data"]["config"]
        assert cfg["agents"] == []  # Bob never sees Alice's overrides (RLS)
