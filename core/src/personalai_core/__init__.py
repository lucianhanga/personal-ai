"""PersonalAI core: orchestration, gateway, security engine, validation, registries.

Depends only on ``personalai_contracts`` (ADR-0001). Must not import the backend app or any
concrete adapter. M0-4 adds the registry/DI machinery: register adapters into :class:`Registries`
and resolve the configured singletons via :func:`build_services`.
"""

from personalai_core.config import CoreConfig
from personalai_core.registries import Registries
from personalai_core.registry import Registry, RegistryError
from personalai_core.retrieval import VectorRetriever
from personalai_core.services import Services, build_services

__version__ = "0.0.0"

__all__ = [
    "CoreConfig",
    "Registries",
    "Registry",
    "RegistryError",
    "Services",
    "VectorRetriever",
    "__version__",
    "build_services",
]
