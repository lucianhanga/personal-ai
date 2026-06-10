"""The composition root wires the built-in tools behind the gateway (no DB needed)."""

from __future__ import annotations

import asyncio
from pathlib import Path

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


def test_http_fetch_loopback_blocked_by_ssrf_guard() -> None:
    # Loopback passes the egress allowlist, but the SSRF guard refuses private/loopback targets
    # (defense against reaching internal services / the cloud metadata endpoint).
    boot = bootstrap(config=CoreConfig())
    grants = [Permission(type=PermissionType.NETWORK, scope="*")]
    call = ToolCall("http_fetch", "1.0.0", {"url": "http://127.0.0.1:9/"})
    result = asyncio.run(boot.gateway.invoke(call, grants=grants, approved=True))
    assert not result.ok and "non-public" in (result.error or "")


def test_ollama_provider_egress_guard_wired_and_allows_loopback() -> None:
    # The composition wires an egress guard onto the Ollama provider; the default loopback host
    # passes it (no raise). A remote OLLAMA_HOST with egress off would be blocked.
    boot = bootstrap(config=CoreConfig())
    provider = boot.registries.model_providers.get("ollama")
    provider._check_egress()  # type: ignore[attr-defined]  # loopback -> allowed


def test_web_search_blocked_by_egress_when_off() -> None:
    boot = bootstrap(config=CoreConfig())  # egress off by default
    grants = [Permission(type=PermissionType.NETWORK, scope="html.duckduckgo.com")]
    result = asyncio.run(
        boot.gateway.invoke(ToolCall("web_search", "1.0.0", {"query": "x"}), grants=grants)
    )
    assert not result.ok and "egress blocked" in (result.error or "")


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


def test_bootstrap_wires_durable_audit_sink(tmp_path: Path) -> None:
    sink = tmp_path / "audit.jsonl"
    boot = bootstrap(config=CoreConfig(audit_log_path=str(sink)))
    boot.audit.append("tool.test", {"x": 1})
    assert sink.exists() and "tool.test" in sink.read_text(encoding="utf-8")


def test_bootstrap_audit_in_memory_without_path() -> None:
    boot = bootstrap(config=CoreConfig())  # no audit_log_path -> in-memory only
    boot.audit.append("tool.test", {})
    assert boot.audit.entries()[-1].type == "tool.test"
