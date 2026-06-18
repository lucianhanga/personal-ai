"""Tool gateway: authorization, validation, egress, timeout, audit (fakes only)."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest

from personalai_contracts.ports import ToolCall, ToolResult
from personalai_contracts.schemas.tools import (
    Permission,
    PermissionType,
    Provenance,
    RiskLevel,
    ToolManifest,
)
from personalai_core import InProcessExecutor, RegisteredTool, Registry, ToolGateway
from personalai_core.security import EgressBlockedError
from personalai_core.security.audit import AuditLog

_PROV = Provenance(maintainer="tests")
_STR_SCHEMA = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}


class _Echo:
    name = "echo"

    async def invoke(self, call: ToolCall) -> ToolResult:
        return ToolResult(ok=True, output={"echo": call.args.get("x", "")})


class _Slow:
    name = "slow"

    async def invoke(self, call: ToolCall) -> ToolResult:
        await asyncio.sleep(1.0)
        return ToolResult(ok=True)


def _manifest(**kw: object) -> ToolManifest:
    base: dict[str, object] = {"name": "echo", "version": "1.0.0", "provenance": _PROV}
    base.update(kw)
    return ToolManifest(**base)  # type: ignore[arg-type]


def _gateway(
    tool: RegisteredTool, *, egress_ok: bool = True, timeout: float = 5.0
) -> tuple[ToolGateway, AuditLog]:
    reg: Registry[RegisteredTool] = Registry("tool")
    reg.register(tool.manifest.name, tool)
    audit = AuditLog()

    def egress(host: str) -> None:
        if not egress_ok:
            raise EgressBlockedError(host)

    return ToolGateway(
        reg, InProcessExecutor(), audit=audit, egress_check=egress, default_timeout=timeout
    ), audit


def _run(coro: Coroutine[Any, Any, ToolResult]) -> ToolResult:
    return asyncio.run(coro)


def test_allowed_call_runs_and_is_audited() -> None:
    gw, audit = _gateway(RegisteredTool(_manifest(inputs=_STR_SCHEMA, risk=RiskLevel.LOW), _Echo()))
    result = _run(gw.invoke(ToolCall("echo", "1.0.0", {"x": "hi"})))
    assert result.ok and result.output == {"echo": "hi"}
    assert any(e.type == "tool.invoke" for e in audit.entries())


def test_unknown_tool_denied() -> None:
    gw, _ = _gateway(RegisteredTool(_manifest(), _Echo()))
    result = _run(gw.invoke(ToolCall("nope", "1.0.0")))
    assert not result.ok and "unknown tool" in (result.error or "")


def test_version_mismatch_denied() -> None:
    gw, _ = _gateway(RegisteredTool(_manifest(), _Echo()))
    result = _run(gw.invoke(ToolCall("echo", "9.9.9")))
    assert not result.ok and "version mismatch" in (result.error or "")


def test_missing_permission_denied() -> None:
    perm = Permission(type=PermissionType.FILESYSTEM, scope="/data")
    gw, audit = _gateway(RegisteredTool(_manifest(permissions=[perm], risk=RiskLevel.LOW), _Echo()))
    result = _run(gw.invoke(ToolCall("echo", "1.0.0", {"x": "hi"})))
    assert not result.ok and "permission not granted" in (result.error or "")
    assert any(e.type == "tool.denied" for e in audit.entries())


def test_granted_permission_allows() -> None:
    perm = Permission(type=PermissionType.FILESYSTEM, scope="/data")
    gw, _ = _gateway(
        RegisteredTool(
            _manifest(permissions=[perm], inputs=_STR_SCHEMA, risk=RiskLevel.LOW), _Echo()
        )
    )
    result = _run(gw.invoke(ToolCall("echo", "1.0.0", {"x": "ok"}), grants=[perm]))
    assert result.ok


def test_wildcard_grant_allows() -> None:
    perm = Permission(type=PermissionType.FILESYSTEM, scope="/data")
    wildcard = Permission(type=PermissionType.FILESYSTEM, scope="*")
    gw, _ = _gateway(RegisteredTool(_manifest(permissions=[perm], risk=RiskLevel.LOW), _Echo()))
    result = _run(gw.invoke(ToolCall("echo", "1.0.0"), grants=[wildcard]))
    assert result.ok


def test_high_risk_requires_approval() -> None:
    gw, _ = _gateway(RegisteredTool(_manifest(risk=RiskLevel.HIGH), _Echo()))
    denied = _run(gw.invoke(ToolCall("echo", "1.0.0")))
    assert not denied.ok and "approval required" in (denied.error or "")
    approved = _run(gw.invoke(ToolCall("echo", "1.0.0"), approved=True))
    assert approved.ok


def test_invalid_input_rejected() -> None:
    gw, _ = _gateway(RegisteredTool(_manifest(inputs=_STR_SCHEMA, risk=RiskLevel.LOW), _Echo()))
    result = _run(gw.invoke(ToolCall("echo", "1.0.0", {"x": 123})))  # x must be string
    assert not result.ok and "invalid input" in (result.error or "")


def test_invalid_input_error_lists_valid_parameters() -> None:
    # The error names the valid parameters so the model can fix a wrong argument name next turn.
    # Empty args can't be auto-coerced (no single mislabeled key), so the call is denied.
    gw, _ = _gateway(RegisteredTool(_manifest(inputs=_STR_SCHEMA, risk=RiskLevel.LOW), _Echo()))
    result = _run(gw.invoke(ToolCall("echo", "1.0.0", {})))  # missing required `x`, nothing to rename
    assert not result.ok
    assert "valid parameters: x (required)" in (result.error or "")


def test_single_mislabeled_arg_is_auto_coerced() -> None:
    # A model sent `input` for the required `x`; the gateway renames the one extra key and runs the
    # tool (the handler sees the corrected name), instead of failing the call.
    gw, _ = _gateway(RegisteredTool(_manifest(inputs=_STR_SCHEMA, risk=RiskLevel.LOW), _Echo()))
    result = _run(gw.invoke(ToolCall("echo", "1.0.0", {"input": "hello"})))
    assert result.ok and result.output == {"echo": "hello"}


def test_egress_blocked_denies() -> None:
    gw, _ = _gateway(
        RegisteredTool(_manifest(egress=["evil.example"], risk=RiskLevel.LOW), _Echo()),
        egress_ok=False,
    )
    result = _run(gw.invoke(ToolCall("echo", "1.0.0")))
    assert not result.ok and "egress blocked" in (result.error or "")


def test_egress_allowed_runs() -> None:
    gw, _ = _gateway(RegisteredTool(_manifest(egress=["api.example"], risk=RiskLevel.LOW), _Echo()))
    assert _run(gw.invoke(ToolCall("echo", "1.0.0"))).ok


def test_invalid_output_rejected() -> None:
    out_schema = {"type": "object", "properties": {"n": {"type": "number"}}, "required": ["n"]}
    gw, _ = _gateway(RegisteredTool(_manifest(outputs=out_schema, risk=RiskLevel.LOW), _Echo()))
    result = _run(
        gw.invoke(ToolCall("echo", "1.0.0"))
    )  # echo returns {"echo": ...}, not {"n": ...}
    assert not result.ok and "invalid output" in (result.error or "")


def test_timeout_is_fail_closed() -> None:
    gw, _ = _gateway(
        RegisteredTool(_manifest(name="slow", risk=RiskLevel.LOW), _Slow()), timeout=0.05
    )
    result = _run(gw.invoke(ToolCall("slow", "1.0.0")))
    assert not result.ok and "timed out" in (result.error or "")


def test_executor_catches_handler_error() -> None:
    class _Boom:
        name = "boom"

        async def invoke(self, call: ToolCall) -> ToolResult:
            raise RuntimeError("kaboom")

    gw, _ = _gateway(RegisteredTool(_manifest(name="boom", risk=RiskLevel.LOW), _Boom()))
    result = _run(gw.invoke(ToolCall("boom", "1.0.0")))
    assert not result.ok and "tool error" in (result.error or "")


@pytest.mark.parametrize("scope", ["/data", "*"])
def test_executor_is_a_tool_executor(scope: str) -> None:
    from personalai_contracts.ports import ToolExecutor

    assert isinstance(InProcessExecutor(), ToolExecutor)
    assert Permission(type=PermissionType.FILESYSTEM, scope=scope).scope == scope
