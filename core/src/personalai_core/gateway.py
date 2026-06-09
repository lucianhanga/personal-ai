"""The Tool/MCP gateway (ADR-0004): the single chokepoint every tool call passes through.

Enforces, in order: tool lookup, version pinning, risk approval, least-privilege permissions,
JSON-Schema input validation, network egress allowlist, a time bound (via the executor seam), and
JSON-Schema output validation — auditing the outcome. Fail-closed: any check that fails returns a
``ToolResult(ok=False, ...)`` and is recorded; nothing executes until every gate passes.

The executor seam keeps tool isolation swappable (in-process now; subprocess/container/remote-MCP
later). Untrusted MCP servers (M6) run out-of-process by protocol and plug in here unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import jsonschema

from personalai_contracts.ports import ToolCall, ToolExecutor, ToolHandler, ToolResult
from personalai_contracts.schemas.tools import Permission, RiskLevel, ToolManifest
from personalai_core.registry import Registry, RegistryError
from personalai_core.security.audit import AuditLog
from personalai_core.security.egress import EgressBlockedError

# Raises EgressBlockedError when a host is not allowed (wraps assert_egress_allowed in the app).
EgressCheck = Callable[[str], None]

_APPROVAL_RISKS = frozenset({RiskLevel.HIGH, RiskLevel.CRITICAL})


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
            try:
                jsonschema.validate(dict(call.args), dict(manifest.inputs))
            except jsonschema.ValidationError as exc:
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
