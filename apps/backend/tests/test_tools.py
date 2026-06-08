"""The composition root wires the built-in tools behind the gateway (no DB needed)."""

from __future__ import annotations

import asyncio

from personalai_backend.composition import bootstrap
from personalai_contracts.ports import ToolCall, ToolResult
from personalai_contracts.schemas.tools import (
    Permission,
    PermissionType,
    Provenance,
    RiskLevel,
    ToolManifest,
)
from personalai_core import CoreConfig, RegisteredTool


def test_gateway_runs_calculator() -> None:
    boot = bootstrap(config=CoreConfig())
    result = asyncio.run(
        boot.gateway.invoke(ToolCall("calculator", "1.0.0", {"expression": "6 * 7"}))
    )
    assert result.ok and result.output["result"] == 42.0


def test_http_fetch_needs_grant_and_approval() -> None:
    boot = bootstrap(config=CoreConfig())  # egress off by default
    call = ToolCall("http_fetch", "1.0.0", {"url": "http://example.com"})

    # HIGH-risk + NETWORK permission: denied without approval/grant.
    denied = asyncio.run(boot.gateway.invoke(call))
    assert not denied.ok

    # With approval + the NETWORK grant the gateway runs it, but egress is off -> handler blocks.
    grants = [Permission(type=PermissionType.NETWORK, scope="*")]
    blocked = asyncio.run(boot.gateway.invoke(call, grants=grants, approved=True))
    assert not blocked.ok and "egress not allowed" in (blocked.error or "")


def test_http_fetch_loopback_passes_egress_then_fetches() -> None:
    # Loopback is always allowed -> egress check passes, the handler attempts the (refused) fetch.
    boot = bootstrap(config=CoreConfig())
    grants = [Permission(type=PermissionType.NETWORK, scope="*")]
    call = ToolCall("http_fetch", "1.0.0", {"url": "http://127.0.0.1:9/"})
    result = asyncio.run(boot.gateway.invoke(call, grants=grants, approved=True))
    assert not result.ok and "fetch failed" in (result.error or "")  # reached the fetch, not egress


def test_gateway_enforces_static_egress_for_a_tool() -> None:
    # A tool that declares a static egress host is blocked by the gateway when egress is off.
    boot = bootstrap(config=CoreConfig())

    class _Pinger:
        name = "pinger"

        async def invoke(self, call: ToolCall) -> ToolResult:
            return ToolResult(ok=True)

    manifest = ToolManifest(
        name="pinger",
        version="1.0.0",
        provenance=Provenance(maintainer="tests"),
        egress=["api.example.com"],
        risk=RiskLevel.LOW,
    )
    boot.registries.tools.register("pinger", RegisteredTool(manifest, _Pinger()))
    result = asyncio.run(boot.gateway.invoke(ToolCall("pinger", "1.0.0")))
    assert not result.ok and "egress blocked" in (result.error or "")
