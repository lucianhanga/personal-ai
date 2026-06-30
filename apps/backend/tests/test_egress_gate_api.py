"""Egress-approval gate over the HTTP API (#377): the 2nd durable gate. When a researcher tool's
outbound call is egress-blocked, /chat suspends with an `approval_request` (reason=egress_approval)
and /chat/{run_id}/resume takes egress_allow_once / egress_allow_always / egress_deny.

Security invariants proven here (P0):
- subject-mismatch resume -> 403 (different subject, SAME tenant);
- the resume body NEVER carries a host (host comes from the checkpoint) — a host in the body is
  ignored;
- allow_always persists the tenant allowlist; allow_once does NOT;
- the SSRF guard still runs after an allow (allow_always on a metadata IP does NOT enable the call).

DB-gated (durable checkpoint lives in Postgres), mirroring test_conversations.py's skipif pattern.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from personalai_backend.app import create_app
from personalai_backend.composition import bootstrap
from personalai_contracts.ports import (
    GenerationRequest,
    GenerationResult,
    ToolCall,
    ToolCallRequest,
    ToolResult,
)
from personalai_contracts.schemas.tools import (
    Permission,
    PermissionType,
    Provenance,
    RiskLevel,
    ToolManifest,
)
from personalai_contracts.testing import FakeModelProvider
from personalai_core import CoreConfig
from personalai_core.gateway import RegisteredTool
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

# A tool that declares a STATIC egress host -> the gateway enforces the egress allowlist for it, so
# a denied host triggers the egress-approval gate (the same mechanism web_search uses).
BLOCKED_HOST = "api.blocked.test"
BLOCKED_FETCH = ToolManifest(
    name="blocked_fetch",
    version="1.0.0",
    provenance=Provenance(maintainer="tests"),
    description="a tool that reaches a fixed external host",
    permissions=(Permission(type=PermissionType.NETWORK, scope="*"),),
    egress=(BLOCKED_HOST,),
    risk=RiskLevel.LOW,
)
# A tool whose static egress host is the cloud metadata IP. Even if a tenant allow_alwayses it (so
# the gateway allowlist passes), the handler's SSRF guard must still refuse it.
METADATA_IP = "169.254.169.254"
METADATA_FETCH = ToolManifest(
    name="metadata_fetch",
    version="1.0.0",
    provenance=Provenance(maintainer="tests"),
    description="a tool whose host is the metadata IP",
    permissions=(Permission(type=PermissionType.NETWORK, scope="*"),),
    egress=(METADATA_IP,),
    risk=RiskLevel.LOW,
)


class _BlockedFetch:
    name = "blocked_fetch"

    async def invoke(self, call: ToolCall) -> ToolResult:
        return ToolResult(ok=True, output={"body": "secret data"})


class _MetadataFetch:
    name = "metadata_fetch"

    async def invoke(self, call: ToolCall) -> ToolResult:
        # Mirror http_fetch's SSRF guard: refuse non-public (metadata/RFC1918/loopback) targets
        # even if the egress allowlist permitted the host. This guard must override the allow.
        import ipaddress

        ip = ipaddress.ip_address(METADATA_IP)
        if ip.is_link_local or ip.is_private or ip.is_loopback or ip.is_reserved:
            return ToolResult(ok=False, error=f"blocked non-public address: {ip}")
        return ToolResult(ok=True, output={"body": "metadata"})


class _ResearcherFetches(FakeModelProvider):
    """In graph mode: the planner/critic produce text; the researcher calls ``tool_name`` once
    (egress-blocked), then on its NEXT turn answers. Drives the egress gate deterministically."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(name="fake")
        self._tool = tool_name
        self._researcher_turns = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        if request.tools:  # researcher turn (only it is offered tools)
            self._researcher_turns += 1
            if self._researcher_turns == 1:
                return GenerationResult(
                    text="",
                    model=request.model,
                    tool_calls=[ToolCallRequest(name=self._tool, arguments={"q": "x"})],
                )
            return GenerationResult(text="Here is the answer.", model=request.model)
        return GenerationResult(text="ok", model=request.model)


def _app(tool: RegisteredTool, provider: FakeModelProvider, agent_mode: str = "multi") -> TestClient:
    boot = bootstrap(
        config=CoreConfig(
            app_mode="hosted",
            agent_mode=agent_mode,
            # The egress-approval gate is now independent of the answer gate (#377 decouple): enable
            # ONLY it, so these tests exercise an egress suspension without also pausing at the
            # answer gate before finalize. It works in BOTH agent modes (single-agent routes through
            # the minimal gated graph), so the same suite runs with agent_mode="single" too.
            agent_egress_gate=True,
            database_url=DB_URL,  # same DB the raw-pool helpers read (conftest isolates to _test)
        )
    )
    boot.registries.model_providers.register("fake", provider, overwrite=True)
    boot.registries.tools.register(tool.manifest.name, tool, overwrite=True)
    return TestClient(create_app(boot), base_url="https://testserver")


_TEST_PW = "pw"  # pragma: allowlist secret  (throwaway password for the test signup/login)


def _signup_login(client: TestClient, email: str) -> None:
    client.post("/api/v1/auth/signup", json={"email": email, "password": _TEST_PW})
    assert (
        client.post("/api/v1/auth/login", json={"email": email, "password": _TEST_PW}).status_code
        == 200
    )


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("pai_csrf") or ""}


def _start_blocked_turn(client: TestClient, tool_name: str) -> tuple[str, str, str]:
    """Start a gated chat turn that egress-blocks; return (run_id, conversation_id, SSE body)."""
    cid = client.post(
        "/api/v1/conversations", json={"title": "egress"}, headers=_csrf(client)
    ).json()["data"]["id"]
    with client.stream(
        "POST",
        "/api/v1/chat",
        headers=_csrf(client),
        json={
            "messages": [{"role": "user", "content": f"use {tool_name}"}],
            "provider": "fake",
            "use_tools": True,
            "conversation_id": cid,
        },
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    return _run_id_from_sse(body), cid, body


def _run_id_from_sse(body: str) -> str:
    for frame in body.split("\n\n"):
        if "event: approval_request" in frame:
            data = next(line for line in frame.splitlines() if line.startswith("data: "))
            return str(json.loads(data[len("data: ") :])["run_id"])
    raise AssertionError(f"no approval_request in SSE body:\n{body}")


def _approval_payload(body: str) -> dict[str, object]:
    for frame in body.split("\n\n"):
        if "event: approval_request" in frame:
            data = next(line for line in frame.splitlines() if line.startswith("data: "))
            return dict(json.loads(data[len("data: ") :]))
    raise AssertionError("no approval_request frame")


def test_egress_block_suspends_with_egress_approval_payload_and_no_leak() -> None:
    # The block surfaces approval_request with reason=egress_approval + blocked_host + tool + args.
    # The server-only resume frame + subject_id are whitelisted OUT of the client SSE.
    with _app(
        RegisteredTool(BLOCKED_FETCH, _BlockedFetch()), _ResearcherFetches("blocked_fetch")
    ) as client:
        _signup_login(client, f"a-{uuid.uuid4().hex[:8]}@x.com")
        _run_id, _cid, body = _start_blocked_turn(client, "blocked_fetch")
        payload = _approval_payload(body)
        assert payload["reason"] == "egress_approval"
        assert payload["blocked_host"] == BLOCKED_HOST
        assert payload["tool"] == "blocked_fetch"
        assert payload["args"] == {"q": "x"}
        assert "frame" not in payload  # server-only resume frame must NOT reach the client
        assert "subject_id" not in payload  # nor the run's subject
        assert '"done": true' not in body  # suspended, not finished


def test_single_agent_egress_block_suspends_and_resumes() -> None:
    # The egress gate works in single-agent mode too (#377 single-agent gated graph): a blocked host
    # durably suspends with the same approval_request, and allow_once resumes + retries the call.
    with _app(
        RegisteredTool(BLOCKED_FETCH, _BlockedFetch()),
        _ResearcherFetches("blocked_fetch"),
        agent_mode="single",
    ) as client:
        _signup_login(client, f"a-{uuid.uuid4().hex[:8]}@x.com")
        run_id, cid, body = _start_blocked_turn(client, "blocked_fetch")
        payload = _approval_payload(body)
        assert payload["reason"] == "egress_approval"
        assert payload["blocked_host"] == BLOCKED_HOST
        assert "subject_id" not in payload  # server-only frame is whitelisted out of the client SSE
        with client.stream(
            "POST",
            f"/api/v1/chat/{run_id}/resume",
            headers=_csrf(client),
            json={"decision": "egress_allow_once", "conversation_id": cid, "provider": "fake"},
        ) as resp:
            assert resp.status_code == 200
            resumed = "".join(resp.iter_text())
        assert "blocked_fetch" in resumed  # retried after the allow and proceeded


def test_resume_allow_once_retries_and_does_not_persist_the_host() -> None:
    with _app(
        RegisteredTool(BLOCKED_FETCH, _BlockedFetch()), _ResearcherFetches("blocked_fetch")
    ) as client:
        _signup_login(client, f"a-{uuid.uuid4().hex[:8]}@x.com")
        run_id, cid, _body = _start_blocked_turn(client, "blocked_fetch")
        with client.stream(
            "POST",
            f"/api/v1/chat/{run_id}/resume",
            headers=_csrf(client),
            json={"decision": "egress_allow_once", "conversation_id": cid, "provider": "fake"},
        ) as resp:
            assert resp.status_code == 200
            resumed = "".join(resp.iter_text())
        # The retried tool succeeded and the turn proceeded to the answer (the 2nd gate / final).
        assert "blocked_fetch" in resumed
        # allow_once is per-request only: the tenant's saved allowlist must NOT contain the host.
        settings = client.get("/api/v1/settings").json()["data"]["settings"]
        hosts = settings.get("allowed_egress_hosts") or []
        assert BLOCKED_HOST not in hosts


def test_resume_allow_always_persists_the_host() -> None:
    with _app(
        RegisteredTool(BLOCKED_FETCH, _BlockedFetch()), _ResearcherFetches("blocked_fetch")
    ) as client:
        _signup_login(client, f"a-{uuid.uuid4().hex[:8]}@x.com")
        run_id, cid, _body = _start_blocked_turn(client, "blocked_fetch")
        with client.stream(
            "POST",
            f"/api/v1/chat/{run_id}/resume",
            headers=_csrf(client),
            json={"decision": "egress_allow_always", "conversation_id": cid, "provider": "fake"},
        ) as resp:
            assert resp.status_code == 200
            "".join(resp.iter_text())
        settings = client.get("/api/v1/settings").json()["data"]["settings"]
        hosts = settings.get("allowed_egress_hosts") or []
        assert BLOCKED_HOST in hosts  # persisted to the tenant allowlist
        assert settings.get("egress_enabled") is True


def test_resume_deny_yields_the_egress_error_and_completes() -> None:
    with _app(
        RegisteredTool(BLOCKED_FETCH, _BlockedFetch()), _ResearcherFetches("blocked_fetch")
    ) as client:
        _signup_login(client, f"a-{uuid.uuid4().hex[:8]}@x.com")
        run_id, cid, _body = _start_blocked_turn(client, "blocked_fetch")
        with client.stream(
            "POST",
            f"/api/v1/chat/{run_id}/resume",
            headers=_csrf(client),
            json={"decision": "egress_deny", "conversation_id": cid, "provider": "fake"},
        ) as resp:
            assert resp.status_code == 200
            resumed = "".join(resp.iter_text())
        # The retried tool was denied (egress error in the trace), and the turn still completed.
        assert "egress" in resumed
        # Deny must NOT have persisted the host.
        settings = client.get("/api/v1/settings").json()["data"]["settings"]
        assert BLOCKED_HOST not in (settings.get("allowed_egress_hosts") or [])


def test_host_in_resume_body_is_ignored_host_comes_from_checkpoint() -> None:
    # Privilege-escalation guard: the resume body carries ONLY a verb. A host-like field a client
    # smuggles in is ignored — the host comes from the checkpoint. So allow_always persists ONLY the
    # checkpoint host, never the attacker's.
    with _app(
        RegisteredTool(BLOCKED_FETCH, _BlockedFetch()), _ResearcherFetches("blocked_fetch")
    ) as client:
        _signup_login(client, f"a-{uuid.uuid4().hex[:8]}@x.com")
        run_id, cid, _body = _start_blocked_turn(client, "blocked_fetch")
        with client.stream(
            "POST",
            f"/api/v1/chat/{run_id}/resume",
            headers=_csrf(client),
            json={
                "decision": "egress_allow_always",
                "conversation_id": cid,
                "provider": "fake",
                "host": "evil.attacker.test",  # extra field: must be ignored by the verb-only model
            },
        ) as resp:
            assert resp.status_code == 200
            "".join(resp.iter_text())
        hosts = (
            client.get("/api/v1/settings").json()["data"]["settings"].get("allowed_egress_hosts")
            or []
        )
        assert BLOCKED_HOST in hosts  # the server-trusted checkpoint host
        assert "evil.attacker.test" not in hosts  # the smuggled host never took effect


def test_ssrf_guard_still_blocks_after_allow_always_on_metadata_host() -> None:
    # allow_always on a metadata/RFC1918 host adds it to the allowlist (the gateway egress passes),
    # but the tool's per-call SSRF guard still refuses it: the allow does not enable the fetch.
    with _app(
        RegisteredTool(METADATA_FETCH, _MetadataFetch()), _ResearcherFetches("metadata_fetch")
    ) as client:
        _signup_login(client, f"a-{uuid.uuid4().hex[:8]}@x.com")
        run_id, cid, _body = _start_blocked_turn(client, "metadata_fetch")
        with client.stream(
            "POST",
            f"/api/v1/chat/{run_id}/resume",
            headers=_csrf(client),
            json={"decision": "egress_allow_always", "conversation_id": cid, "provider": "fake"},
        ) as resp:
            assert resp.status_code == 200
            resumed = "".join(resp.iter_text())
        # The host was allowlisted (allow_always), yet the fetch was refused by the SSRF guard.
        assert METADATA_IP in (
            client.get("/api/v1/settings").json()["data"]["settings"].get("allowed_egress_hosts")
            or []
        )
        assert "blocked non-public address" in resumed  # the SSRF guard fired despite the allow


def test_subject_mismatch_resume_is_forbidden_same_tenant() -> None:
    # P0: a run may only be resumed by the SAME subject, even within one tenant. Bob is created as a
    # SECOND member of Alice's tenant ONLY (no signup -> no tenant of his own), so when he resumes
    # Alice's suspended run the checkpoint IS found (same tenant) but the subject differs -> 403.
    from personalai_backend.auth.passwords import hash_password
    from personalai_storage_postgres import PgTenantStore

    alice_email = f"alice-{uuid.uuid4().hex[:8]}@x.com"
    bob_email = f"bob-{uuid.uuid4().hex[:8]}@x.com"
    with _app(
        RegisteredTool(BLOCKED_FETCH, _BlockedFetch()), _ResearcherFetches("blocked_fetch")
    ) as alice:
        _signup_login(alice, alice_email)
        run_id, cid, _body = _start_blocked_turn(alice, "blocked_fetch")

    # Add Bob as a member of ALICE's tenant ONLY (so login resolves him into her tenant). Done after
    # the TestClient context closes so the manual asyncpg pool runs on its own event loop.
    async def _add_bob_to_alice_tenant() -> None:
        pool = await create_pool(DB_URL)
        try:
            store = PgTenantStore(pool)
            alice_cred = await store.get_password_hash(alice_email)
            assert alice_cred is not None
            tenant_id, _role = (await store.memberships_for_subject(alice_cred[0]))[0]
            bob = await store.create_subject(email=bob_email)
            await store.add_membership(tenant_id, bob.id, role="member")
            await store.set_password_hash(bob.id, hash_password("pw"))
        finally:
            await pool.close()

    asyncio.run(_add_bob_to_alice_tenant())

    # Bob logs in (resolved into Alice's tenant) and tries to resume Alice's run -> 403.
    with _app(
        RegisteredTool(BLOCKED_FETCH, _BlockedFetch()), _ResearcherFetches("blocked_fetch")
    ) as bob:
        assert (
            bob.post(
                "/api/v1/auth/login", json={"email": bob_email, "password": _TEST_PW}
            ).status_code
            == 200
        )
        denied = bob.post(
            f"/api/v1/chat/{run_id}/resume",
            headers=_csrf(bob),
            json={"decision": "egress_allow_once", "conversation_id": cid, "provider": "fake"},
        )
        assert denied.status_code == 403
