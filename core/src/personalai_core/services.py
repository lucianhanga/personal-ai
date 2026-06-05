"""Resolve the active singleton adapters from the registries (composition helper).

``build_services`` takes the populated registries plus a :class:`CoreConfig` and returns the
selected singleton adapters. It is fail-closed: if a configured adapter name is not registered,
the underlying :class:`~personalai_core.registry.RegistryError` propagates. Collection seams
(tools, agent roles, modality handlers) are used directly from the registries per request.
"""

from __future__ import annotations

from dataclasses import dataclass

from personalai_contracts.ports import (
    ModelProvider,
    ObjectStore,
    Retriever,
    VectorRepository,
)
from personalai_core.config import CoreConfig
from personalai_core.registries import Registries


@dataclass(frozen=True)
class Services:
    """The active singleton adapters selected by configuration."""

    model_provider: ModelProvider
    retriever: Retriever
    vector_repository: VectorRepository
    object_store: ObjectStore


def build_services(registries: Registries, config: CoreConfig) -> Services:
    """Resolve the configured singleton adapters from ``registries`` (fail-closed)."""
    return Services(
        model_provider=registries.model_providers.get(config.model_provider),
        retriever=registries.retrievers.get(config.retriever),
        vector_repository=registries.vector_repositories.get(config.vector_repository),
        object_store=registries.object_stores.get(config.object_store),
    )
