"""The identity value objects (SecurityContext / AuthResult / Session)."""

from __future__ import annotations

from datetime import UTC, datetime

from personalai_contracts.ports import AuthResult, SecurityContext, Session


def test_security_context_defaults_and_fields() -> None:
    ctx = SecurityContext(subject_id="s1", tenant_id="t1")
    assert ctx.subject_id == "s1" and ctx.tenant_id == "t1"
    assert ctx.auth_kind == "cookie" and ctx.scopes == frozenset() and ctx.session_id is None
    scoped = SecurityContext(
        "s", "t", auth_kind="api_key", scopes=frozenset({"read"}), session_id="x"
    )
    assert scoped.auth_kind == "api_key" and "read" in scoped.scopes and scoped.session_id == "x"


def test_auth_result_and_session() -> None:
    assert AuthResult(subject_id="s", tenant_id="t").tenant_id == "t"
    now = datetime.now(UTC)
    sess = Session(id="sid", subject_id="s", tenant_id="t", expires_at=now)
    assert sess.id == "sid" and sess.expires_at == now
