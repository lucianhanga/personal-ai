"""build_services resolves configured adapters and swapping needs no core change.

Uses the reference fakes from personalai_contracts.testing as stand-in adapters.
"""

from __future__ import annotations

import pytest

from personalai_contracts.testing import (
    FakeModelProvider,
    FakeRetriever,
    InMemoryObjectStore,
    InMemoryVectorRepository,
)
from personalai_core import CoreConfig, Registries, RegistryError, build_services


def _populate(registries: Registries, provider_name: str) -> None:
    registries.model_providers.register(provider_name, FakeModelProvider(name=provider_name))
    registries.retrievers.register("fake", FakeRetriever([]))
    registries.vector_repositories.register("memory", InMemoryVectorRepository())
    registries.object_stores.register("memory", InMemoryObjectStore())


def _config(provider_name: str) -> CoreConfig:
    return CoreConfig(
        model_provider=provider_name,
        retriever="fake",
        vector_repository="memory",
        object_store="memory",
    )


def test_build_services_resolves_selected_adapters() -> None:
    registries = Registries()
    _populate(registries, "primary")
    services = build_services(registries, _config("primary"))
    assert services.model_provider.name == "primary"
    assert services.vector_repository is registries.vector_repositories.get("memory")


def test_swapping_adapter_needs_no_core_change() -> None:
    # Two providers registered under different names; config alone selects which is active.
    registries = Registries()
    registries.model_providers.register("a", FakeModelProvider(name="a"))
    registries.model_providers.register("b", FakeModelProvider(name="b"))
    registries.retrievers.register("fake", FakeRetriever([]))
    registries.vector_repositories.register("memory", InMemoryVectorRepository())
    registries.object_stores.register("memory", InMemoryObjectStore())

    assert build_services(registries, _config("a")).model_provider.name == "a"
    assert build_services(registries, _config("b")).model_provider.name == "b"


def test_unregistered_selection_is_fail_closed() -> None:
    registries = Registries()
    _populate(registries, "primary")
    with pytest.raises(RegistryError, match="no model provider registered as 'missing'"):
        build_services(registries, _config("missing"))
