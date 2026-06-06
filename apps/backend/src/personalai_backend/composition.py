"""Composition root: build the registries, register adapters, resolve services.

This is the one place that knows about concrete adapters (ADR-0001). At M0-4 no production
adapters exist yet, so :func:`register_adapters` is an intentionally empty seam; concrete
adapters (Ollama provider, pgvector repository, local object store, ...) are registered here
starting in M0-5. Tests prove the wiring by registering adapters and resolving them without any
change to the core.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from personalai_core import CoreConfig, Registries


@dataclass(frozen=True)
class Bootstrap:
    """The assembled application wiring."""

    registries: Registries
    config: CoreConfig


def register_adapters(registries: Registries, config: CoreConfig) -> None:
    """Register concrete adapters into the registries (the only place that knows about them).

    M1 registers the local Ollama provider. More adapters (remote/OpenAI via the same
    ``ModelProvider`` seam, retrievers, storage, ...) are added here in later milestones.
    """
    from personalai_provider_ollama import OllamaProvider

    registries.model_providers.register("ollama", OllamaProvider(base_url=config.ollama_host))


def bootstrap(
    config: CoreConfig | None = None,
    environ: Mapping[str, str] | None = None,
) -> Bootstrap:
    """Build the application wiring: config from env, empty registries, registered adapters."""
    resolved_config = config or CoreConfig.from_env(environ if environ is not None else os.environ)
    registries = Registries()
    register_adapters(registries, resolved_config)
    return Bootstrap(registries=registries, config=resolved_config)
