"""Composition root: build the registries, register adapters, resolve services.

This is the one place that knows about concrete adapters (ADR-0001): :func:`register_adapters`
wires the Ollama + OpenAI providers, pgvector repository, built-in tools, and the tool gateway.
New capabilities are added here as new adapters behind existing ports, without changing the core.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from personalai_core import CoreConfig, InProcessExecutor, Registries, ToolGateway
from personalai_core.security import (
    AuditLog,
    EgressBlockedError,
    assert_egress_allowed,
    effective_egress_config,
)


@dataclass(frozen=True)
class Bootstrap:
    """The assembled application wiring."""

    registries: Registries
    config: CoreConfig
    gateway: ToolGateway
    audit: AuditLog


def register_adapters(registries: Registries, config: CoreConfig) -> None:
    """Register concrete adapters into the registries (the only place that knows about them).

    M1 registers the local Ollama provider. More adapters (remote/OpenAI via the same
    ``ModelProvider`` seam, retrievers, storage, ...) are added here in later milestones.
    """
    from personalai_provider_ollama import OllamaProvider

    # Egress-guard the Ollama host too: loopback (the local default) passes; a remote OLLAMA_HOST is
    # blocked unless egress is enabled + allowlisted (the provider cannot import the core).
    def _ollama_egress(host: str) -> None:
        assert_egress_allowed(config, host)

    registries.model_providers.register(
        "ollama",
        OllamaProvider(
            base_url=config.ollama_host,
            num_ctx=config.ollama_num_ctx,
            keep_alive=config.ollama_keep_alive,
            temperature=config.ollama_temperature,
            top_p=config.ollama_top_p,
            top_k=config.ollama_top_k,
            egress_guard=_ollama_egress,
        ),
    )

    # Remote OpenAI-compatible provider, only when an API key is configured. Its egress guard is
    # wired to the core egress allowlist (the provider itself cannot import the core).
    if config.openai_api_key:
        from personalai_provider_openai import OpenAICompatProvider

        def _openai_egress(host: str) -> None:
            assert_egress_allowed(config, host)

        registries.model_providers.register(
            "openai",
            OpenAICompatProvider(
                api_key=config.openai_api_key,
                base_url=config.openai_base_url,
                egress_guard=_openai_egress,
            ),
        )

    # Built-in tools, behind the gateway (ADR-0004).
    from personalai_core import RegisteredTool
    from personalai_tool_builtin import (
        CALCULATOR_MANIFEST,
        HTTP_FETCH_MANIFEST,
        WEB_SEARCH_MANIFEST,
        Calculator,
        HttpFetch,
        WebSearch,
    )

    registries.tools.register("calculator", RegisteredTool(CALCULATOR_MANIFEST, Calculator()))
    # web_search declares a static egress host, so the gateway enforces the egress allowlist for it.
    registries.tools.register("web_search", RegisteredTool(WEB_SEARCH_MANIFEST, WebSearch()))

    def _fetch_egress_allowed(host: str) -> bool:
        # Honor the request tenant's effective egress (#290), falling back to boot config.
        try:
            assert_egress_allowed(effective_egress_config(config), host)
        except EgressBlockedError:
            return False
        return True

    registries.tools.register(
        "http_fetch", RegisteredTool(HTTP_FETCH_MANIFEST, HttpFetch(_fetch_egress_allowed))
    )


def bootstrap(
    config: CoreConfig | None = None,
    environ: Mapping[str, str] | None = None,
) -> Bootstrap:
    """Build the application wiring: config from env, empty registries, registered adapters."""
    resolved_config = config or CoreConfig.from_env(environ if environ is not None else os.environ)
    registries = Registries()
    register_adapters(registries, resolved_config)

    # Durable audit: append events to a JSONL sink (survives restart) when a path is configured.
    audit_path = Path(resolved_config.audit_log_path) if resolved_config.audit_log_path else None
    audit = AuditLog(sink_path=audit_path)

    def _egress_check(host: str) -> None:
        # Honor the request tenant's effective egress (#290), falling back to boot config.
        assert_egress_allowed(effective_egress_config(resolved_config), host)

    gateway = ToolGateway(
        registries.tools, InProcessExecutor(), audit=audit, egress_check=_egress_check
    )
    # Speech-to-text (M9.2): the transcriber is built per-request from the tenant's effective config
    # (the whisper endpoint/model are per-tenant settings, #298), so it is not assembled here.
    return Bootstrap(registries=registries, config=resolved_config, gateway=gateway, audit=audit)
