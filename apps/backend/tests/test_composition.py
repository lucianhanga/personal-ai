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
