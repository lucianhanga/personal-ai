"""Composition root: build the registries, register adapters, resolve services.

This is the one place that knows about concrete adapters (ADR-0001): :func:`register_adapters`
wires the Ollama + OpenAI providers, pgvector repository, built-in tools, and the tool gateway.
New capabilities are added here as new adapters behind existing ports, without changing the core.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from personalai_core import CoreConfig, InProcessExecutor, Registries, ToolGateway
from personalai_core.security import (
    AuditLog,
    EgressBlockedError,
    assert_egress_allowed,
    effective_egress_config,
)

if TYPE_CHECKING:
    from personalai_tool_builtin import WebSearchProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Bootstrap:
    """The assembled application wiring."""

    registries: Registries
    config: CoreConfig
    gateway: ToolGateway
    audit: AuditLog


def _build_web_search_provider(config: CoreConfig) -> WebSearchProvider:
    """Select the web_search backend from config (#395), falling back to DuckDuckGo when a required
    setting is missing (logged, never crashes) so a misconfigured provider degrades gracefully.

    - ``searxng`` requires ``web_search_base_url`` (a self-hosted instance);
    - ``tavily`` requires ``web_search_api_key``;
    - anything else (incl. the default) is zero-setup DuckDuckGo.
    """
    from personalai_tool_builtin import DuckDuckGoSearch, SearxngSearch, TavilySearch

    provider = (config.web_search_provider or "duckduckgo").strip().lower()
    if provider == "searxng":
        if config.web_search_base_url:
            return SearxngSearch(config.web_search_base_url)
        logger.warning(
            "web_search provider 'searxng' selected but PERSONALAI_WEB_SEARCH_BASE_URL is unset; "
            "falling back to DuckDuckGo."
        )
        return DuckDuckGoSearch()
    if provider == "tavily":
        if config.web_search_api_key:
            return TavilySearch(config.web_search_api_key)
        logger.warning(
            "web_search provider 'tavily' selected but PERSONALAI_WEB_SEARCH_API_KEY is unset; "
            "falling back to DuckDuckGo."
        )
        return DuckDuckGoSearch()
    if provider != "duckduckgo":
        logger.warning("unknown web_search provider %r; falling back to DuckDuckGo.", provider)
    return DuckDuckGoSearch()


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
            # Runaway-generation guard, Layers 1-2 (#414): repeat penalties + a hard per-turn output
            # ceiling so an unbounded/looping generation is discouraged and capped.
            repeat_penalty=config.ollama_repeat_penalty,
            repeat_last_n=config.ollama_repeat_last_n,
            max_output_tokens=config.max_output_tokens,
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
                # Runaway-generation guard, Layers 1-2 (#414): repetition penalties + per-turn cap.
                frequency_penalty=config.openai_frequency_penalty,
                presence_penalty=config.openai_presence_penalty,
                max_output_tokens=config.max_output_tokens,
            ),
        )

    # Built-in tools, behind the gateway (ADR-0004).
    from personalai_core import RegisteredTool
    from personalai_tool_builtin import (
        CALCULATOR_MANIFEST,
        HTTP_FETCH_MANIFEST,
        Calculator,
        HttpFetch,
        WebSearch,
        web_search_manifest,
    )

    registries.tools.register("calculator", RegisteredTool(CALCULATOR_MANIFEST, Calculator()))
    # web_search: select the provider from config, then build the manifest with the ACTIVE
    # provider's egress host so the gateway enforces the allowlist against the host actually
    # contacted (the gateway iterates manifest.egress).
    search_provider = _build_web_search_provider(config)
    registries.tools.register(
        "web_search",
        RegisteredTool(
            web_search_manifest(search_provider.host),
            WebSearch(search_provider, max_results=config.web_search_max_results),
        ),
    )

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
