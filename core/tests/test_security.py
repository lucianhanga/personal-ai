"""Security primitives: redaction, egress control, append-only audit log."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from personalai_core import CoreConfig
from personalai_core.security import (
    REDACTED,
    AuditLog,
    EgressBlockedError,
    assert_egress_allowed,
    redact,
)


def test_redact_masks_sensitive_keys_recursively() -> None:
    data = {
        "user": "alice",
        "auth_token": "supersecret",
        "nested": {"api_key": "abc", "ok": 1},
        "list": [{"password": "p"}, {"safe": "v"}],
    }
    out = redact(data)
    assert out["user"] == "alice"
    assert out["auth_token"] == REDACTED
    assert out["nested"]["api_key"] == REDACTED
    assert out["nested"]["ok"] == 1
    assert out["list"][0]["password"] == REDACTED
    assert out["list"][1]["safe"] == "v"


def test_redact_leaves_plain_scalars_and_strings() -> None:
    assert redact("just a string with token-like word") == "just a string with token-like word"
    assert redact(42) == 42


def test_egress_blocked_by_default() -> None:
    with pytest.raises(EgressBlockedError, match="egress is disabled"):
        assert_egress_allowed(CoreConfig(), host="api.example.com")


def test_egress_allowed_when_enabled() -> None:
    assert_egress_allowed(CoreConfig(egress_enabled=True), host="api.example.com")  # no raise


def test_egress_allowlist_enforced() -> None:
    config = CoreConfig(egress_enabled=True, allowed_egress_hosts=("ok.example",))
    assert_egress_allowed(config, host="ok.example")  # allowed
    assert_egress_allowed(config, host="OK.Example")  # case-insensitive
    with pytest.raises(EgressBlockedError, match="not in the egress allowlist"):
        assert_egress_allowed(config, host="evil.example")


def test_egress_allowlist_fails_closed_on_unknown_host() -> None:
    # With an allowlist set, a request that does not name a host must be refused (HIGH-2).
    config = CoreConfig(egress_enabled=True, allowed_egress_hosts=("ok.example",))
    with pytest.raises(EgressBlockedError, match="no host was provided"):
        assert_egress_allowed(config, host=None)


def test_redact_caps_recursion_depth() -> None:
    deep: dict[str, object] = {}
    node = deep
    for _ in range(200):
        child: dict[str, object] = {}
        node["next"] = child
        node = child
    # Must not raise RecursionError; deep substructure is replaced with a sentinel.
    out = redact(deep)
    assert out is not None


def test_audit_log_appends_and_redacts() -> None:
    log = AuditLog()
    log.append("tool_call", {"tool": "fs.read", "args": {"token": "secret"}}, actor="agent")
    log.append("egress", {"host": "example.com"})
    entries = log.entries()
    assert len(entries) == 2
    assert entries[0].type == "tool_call"
    assert entries[0].actor == "agent"
    assert entries[0].payload["args"]["token"] == REDACTED


def test_audit_log_file_sink_is_append_only_jsonl(tmp_path: Path) -> None:
    sink = tmp_path / "audit.jsonl"
    log = AuditLog(sink_path=sink)
    log.append("a", {"x": 1})
    log.append("b", {"secret": "nope"})
    lines = sink.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    second = json.loads(lines[1])
    assert second["type"] == "b"
    assert second["payload"]["secret"] == REDACTED


def test_audit_sink_is_owner_only(tmp_path: Path) -> None:
    sink = tmp_path / "audit.jsonl"
    AuditLog(sink_path=sink).append("x", {"a": 1})
    mode = sink.stat().st_mode & 0o777
    assert mode == 0o600, f"audit sink should be owner-only, got {oct(mode)}"


def test_audit_reopens_existing_sink_without_truncating(tmp_path: Path) -> None:
    sink = tmp_path / "audit.jsonl"
    AuditLog(sink_path=sink).append("first", {})
    # A new AuditLog on the same existing path must append, not recreate/truncate.
    AuditLog(sink_path=sink).append("second", {})
    assert len(sink.read_text(encoding="utf-8").strip().splitlines()) == 2
