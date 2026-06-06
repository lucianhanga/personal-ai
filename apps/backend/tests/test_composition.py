"""The composition root assembles registries + config and accepts adapter registration."""

from __future__ import annotations

from personalai_backend import bootstrap
from personalai_contracts.testing import (
    FakeModelProvider,
    FakeRetriever,
    InMemoryObjectStore,
    InMemoryVectorRepository,
)
from personalai_core import CoreConfig, build_services


def test_bootstrap_reads_config_from_env() -> None:
    boot = bootstrap(environ={"PERSONALAI_MODEL_PROVIDER": "fake"})
    assert boot.config.model_provider == "fake"
    # M1 registers the Ollama provider by default.
    assert "ollama" in boot.registries.model_providers


def test_bootstrap_wiring_resolves_registered_adapters() -> None:
    config = CoreConfig(
        model_provider="fake",
        retriever="fake",
        vector_repository="memory",
        object_store="memory",
    )
    boot = bootstrap(config=config)
    # Registering adapters into the bootstrapped registries needs no core/backend change.
    boot.registries.model_providers.register("fake", FakeModelProvider(name="fake"))
    boot.registries.retrievers.register("fake", FakeRetriever([]))
    boot.registries.vector_repositories.register("memory", InMemoryVectorRepository())
    boot.registries.object_stores.register("memory", InMemoryObjectStore())

    services = build_services(boot.registries, boot.config)
    assert services.model_provider.name == "fake"
