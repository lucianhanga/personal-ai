"""The Tool/MCP gateway (ADR-0004): the single chokepoint every tool call passes through.

Enforces, in order: tool lookup, version pinning, risk approval, least-privilege permissions,
JSON-Schema input validation, network egress allowlist, a time bound (via the executor seam), and
JSON-Schema output validation — auditing the outcome. Fail-closed: any check that fails returns a
``ToolResult(ok=False, ...)`` and is recorded; nothing executes until every gate passes.

The executor seam keeps tool isolation swappable (in-process now; subprocess/container/remote-MCP
later). Untrusted MCP servers (M7) run out-of-process by protocol and plug in here unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import jsonschema

from personalai_contracts.ports import ToolCall, ToolExecutor, ToolHandler, ToolResult
from personalai_contracts.schemas.tools import Permission, RiskLevel, ToolManifest
from personalai_core.registry import Registry, RegistryError
from personalai_core.security.audit import AuditLog
from personalai_core.security.egress import EgressBlockedError

# Raises EgressBlockedError when a host is not allowed (wraps assert_egress_allowed in the app).
EgressCheck = Callable[[str], None]

_APPROVAL_RISKS = frozenset({RiskLevel.HIGH, RiskLevel.CRITICAL})


def _coerce_args(args: Mapping[str, Any], schema: Mapping[str, Any]) -> dict[str, Any] | None:
    """Best-effort fixes for common model mistakes so a call succeeds instead of being rejected:
    clamp a numeric argument to the schema's minimum/maximum (e.g. the model asked for max_results=3
    when the tool requires >=5), and rename a single mislabeled argument (e.g. ``input`` for the
    required ``query``). Returns the corrected args, or None when nothing clearly applies."""
    props = schema.get("properties") or {}
    out: dict[str, Any] = dict(args)
    changed = False
    # Clamp out-of-range numbers (not bools) to the schema bound.
    for key, val in list(out.items()):
        spec = props.get(key)
        if isinstance(spec, dict) and isinstance(val, int | float) and not isinstance(val, bool):
            lo, hi = spec.get("minimum"), spec.get("maximum")
            if isinstance(lo, int | float) and val < lo:
                out[key] = lo
                changed = True
            elif isinstance(hi, int | float) and val > hi:
                out[key] = hi
                changed = True
    # Rename a single mislabeled argument (exactly one required missing + one unknown key).
    required = schema.get("required") or []
    missing = [r for r in required if r not in out]
    extra = [k for k in out if k not in props]
    if len(missing) == 1 and len(extra) == 1:
        out[missing[0]] = out.pop(extra[0])
        changed = True
    return out if changed else None


@dataclass(frozen=True)
class RegisteredTool:
    """A tool's manifest bound to the handler that runs it."""

    manifest: ToolManifest
    handler: ToolHandler


def _is_granted(required: Permission, grants: Sequence[Permission]) -> bool:
    return any(g.type == required.type and g.scope in (required.scope, "*") for g in grants)


class InProcessExecutor:
    """Runs the handler in this process with a timeout (sandbox tier 0). Fail-closed."""

    async def execute(self, handler: ToolHandler, call: ToolCall, *, timeout: float) -> ToolResult:
        try:
            return await asyncio.wait_for(handler.invoke(call), timeout=timeout)
        except TimeoutError:
            return ToolResult(ok=False, error=f"tool timed out after {timeout}s")
        except Exception as exc:  # noqa: BLE001 - the gateway is the chokepoint; never leak/raise
            return ToolResult(ok=False, error=f"tool error: {exc}")


class ToolGateway:
    """Authorize, validate, run, and audit a single tool invocation."""

    def __init__(
        self,
        tools: Registry[RegisteredTool],
        executor: ToolExecutor,
        *,
        audit: AuditLog,
        egress_check: EgressCheck,
        default_timeout: float = 30.0,
    ) -> None:
        self._tools = tools
        self._executor = executor
        self._audit = audit
        self._egress = egress_check
        self._timeout = default_timeout

    async def invoke(
        self,
        call: ToolCall,
        *,
        grants: Sequence[Permission] = (),
        approved: bool = False,
    ) -> ToolResult:
        def deny(reason: str) -> ToolResult:
            self._audit.append(
                "tool.denied", {"tool": call.tool, "reason": reason, "args": dict(call.args)}
            )
            return ToolResult(ok=False, error=reason)

        try:
            registered = self._tools.get(call.tool)
        except RegistryError:
            return deny(f"unknown tool: {call.tool}")
        manifest = registered.manifest

        if call.version != manifest.version:
            return deny(f"version mismatch: requested {call.version}, have {manifest.version}")
        if manifest.risk in _APPROVAL_RISKS and not approved:
            return deny(f"approval required for {manifest.risk.value}-risk tool")
        for permission in manifest.permissions:
            if not _is_granted(permission, grants):
                return deny(f"permission not granted: {permission.type.value}:{permission.scope}")
        if manifest.inputs:
            schema = dict(manifest.inputs)
            try:
                jsonschema.validate(dict(call.args), schema)
            except jsonschema.ValidationError as exc:
                # Auto-fix common model slips (a number out of the schema's min/max, or one
                # mislabeled argument name); otherwise deny with the valid parameters listed so the
                # model can self-correct on its next turn.
                coerced = _coerce_args(dict(call.args), schema)
                if coerced is not None:
                    try:
                        jsonschema.validate(coerced, schema)
                        call = ToolCall(call.tool, call.version, coerced)
                    except jsonschema.ValidationError:
                        coerced = None
                if coerced is None:
                    props = schema.get("properties") or {}
                    required = set(schema.get("required") or [])
                    if props:
                        spec = ", ".join(
                            f"{k}{' (required)' if k in required else ''}" for k in props
                        )
                        return deny(f"invalid input: {exc.message}. valid parameters: {spec}")
                    return deny(f"invalid input: {exc.message}")
        for host in manifest.egress:
            try:
                self._egress(host)
            except EgressBlockedError as exc:
                return deny(f"egress blocked: {exc}")

        result = await self._executor.execute(registered.handler, call, timeout=self._timeout)

        if result.ok and manifest.outputs:
            try:
                jsonschema.validate(dict(result.output), dict(manifest.outputs))
            except jsonschema.ValidationError as exc:
                self._audit.append(
                    "tool.invoke", {"tool": call.tool, "ok": False, "error": "invalid output"}
                )
                return ToolResult(ok=False, error=f"invalid output: {exc.message}")

        self._audit.append(
            "tool.invoke",
            {
                "tool": call.tool,
                "version": call.version,
                "args": dict(call.args),
                "ok": result.ok,
                "error": result.error,
            },
        )
        return result
