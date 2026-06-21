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


def _coerce_to_type(value: Any, ty: Any) -> Any:
    """Coerce a value toward the JSON-Schema ``type`` for common model slips (a scalar where an
    array is wanted, a numeric string for a number, a string for a number, "true"/"false" for a
    boolean). Returns the value unchanged when no safe coercion applies; validation still runs
    afterwards, so a wrong coercion is rejected rather than silently used."""
    if ty == "array" and not isinstance(value, list):
        return [value]  # e.g. urls: "http://x" -> ["http://x"]
    if ty in ("integer", "number") and isinstance(value, str):
        try:
            return int(value.strip()) if ty == "integer" else float(value.strip())
        except ValueError:
            return value
    if ty == "string" and isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    if ty == "boolean" and isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return value


def _coerce_args(args: Mapping[str, Any], schema: Mapping[str, Any]) -> dict[str, Any] | None:
    """Best-effort fixes for common model mistakes so a call succeeds instead of being rejected,
    applied to ANY tool by reading its schema: rename one mislabeled argument (``input`` for the
    required ``query``), coerce a value to the declared type (scalar->array, string<->number,
    "true"->bool), and clamp a number to the schema's minimum/maximum. Returns the corrected args,
    or None when nothing applies. The result is re-validated by the caller, so it is always safe."""
    props = schema.get("properties") or {}
    out: dict[str, Any] = dict(args)
    changed = False
    # 1) Rename a single mislabeled argument so it matches a schema property (then it can be typed).
    required = schema.get("required") or []
    missing = [r for r in required if r not in out]
    extra = [k for k in out if k not in props]
    if len(missing) == 1 and len(extra) == 1:
        out[missing[0]] = out.pop(extra[0])
        changed = True
    # 2) Per-property: coerce toward the declared type, then clamp numbers to the bound.
    for key, val in list(out.items()):
        spec = props.get(key)
        if not isinstance(spec, dict):
            continue
        coerced = _coerce_to_type(val, spec.get("type"))
        if coerced != val:
            out[key] = coerced
            val = coerced
            changed = True
        if isinstance(val, int | float) and not isinstance(val, bool):
            lo, hi = spec.get("minimum"), spec.get("maximum")
            if isinstance(lo, int | float) and val < lo:
                out[key] = lo
                changed = True
            elif isinstance(hi, int | float) and val > hi:
                out[key] = hi
                changed = True
    return out if changed else None


def _input_error(exc: jsonschema.ValidationError, schema: Mapping[str, Any]) -> str:
    """A denial message that lists the valid parameters (and, for an enum, the allowed values) so
    the model can self-correct on its next turn."""
    msg = f"invalid input: {exc.message}."
    if exc.validator == "enum" and isinstance(exc.validator_value, list):
        field = exc.path[-1] if exc.path else "value"
        msg += f" {field} must be one of: {', '.join(map(str, exc.validator_value))}."
    props = schema.get("properties") or {}
    if props:
        required = set(schema.get("required") or [])
        spec = ", ".join(f"{k}{' (required)' if k in required else ''}" for k in props)
        msg += f" valid parameters: {spec}"
    return msg


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
                # Auto-fix common model slips (type mismatches, out-of-range numbers, one mislabeled
                # argument); otherwise deny with the valid parameters (and, for an enum, the allowed
                # values) so the model can self-correct on its next turn.
                coerced = _coerce_args(dict(call.args), schema)
                if coerced is not None:
                    try:
                        jsonschema.validate(coerced, schema)
                        call = ToolCall(call.tool, call.version, coerced)
                    except jsonschema.ValidationError:
                        coerced = None
                if coerced is None:
                    return deny(_input_error(exc, schema))
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
