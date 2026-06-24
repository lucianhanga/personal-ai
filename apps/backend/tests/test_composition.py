"""The composition root assembles registries + config and accepts adapter registration."""

from __future__ import annotations

from personalai_backend import bootstrap
from personalai_contracts.testing import FakeModelProvider, FakeRetriever
from personalai_core import CoreConfig


def test_bootstrap_reads_config_from_env() -> None:
    boot = bootstrap(environ={"PERSONALAI_MODEL_PROVIDER": "fake"})
    assert boot.config.model_provider == "fake"
    # M1 registers the Ollama provider by default.
    assert "ollama" in boot.registries.model_providers


def test_registered_adapters_resolve_by_name() -> None:
    # Adding a capability is just registering an adapter behind a port — no core/backend change.
    boot = bootstrap(config=CoreConfig(model_provider="fake"))
    boot.registries.model_providers.register("fake", FakeModelProvider(name="fake"))
    boot.registries.retrievers.register("fake", FakeRetriever([]))
    assert boot.registries.model_providers.get("fake").name == "fake"
    assert "fake" in boot.registries.retrievers


def test_web_search_defaults_to_duckduckgo_egress() -> None:
    # Default config: zero-setup DuckDuckGo, egress pinned to its host (#395 backward-compat).
    boot = bootstrap(config=CoreConfig())
    manifest = boot.registries.tools.get("web_search").manifest
    assert manifest.egress == ("html.duckduckgo.com",)


def test_web_search_searxng_without_base_url_falls_back_to_ddg() -> None:
    # A misconfigured provider degrades to DuckDuckGo instead of crashing the boot.
    boot = bootstrap(config=CoreConfig(web_search_provider="searxng"))
    manifest = boot.registries.tools.get("web_search").manifest
    assert manifest.egress == ("html.duckduckgo.com",)


def test_web_search_searxng_with_base_url_pins_its_host() -> None:
    boot = bootstrap(
        config=CoreConfig(
            web_search_provider="searxng", web_search_base_url="http://127.0.0.1:8888"
        )
    )
    manifest = boot.registries.tools.get("web_search").manifest
    assert manifest.egress == ("127.0.0.1",)
    assert manifest.permissions[0].scope == "127.0.0.1"


def test_web_search_tavily_with_key_pins_api_host() -> None:
    boot = bootstrap(
        config=CoreConfig(
            web_search_provider="tavily",
            web_search_api_key="tvly-secret",  # pragma: allowlist secret
        )
    )
    manifest = boot.registries.tools.get("web_search").manifest
    assert manifest.egress == ("api.tavily.com",)
