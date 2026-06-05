"""Core configuration: which adapters are active, and runtime safety defaults.

Config-driven selection (ADR-0001): the composition root reads :class:`CoreConfig` and resolves
the active singleton adapters from the registries. Security defaults are local-first: bind to
loopback and keep network egress disabled unless explicitly enabled (ADR / THREAT-MODEL).
Richer settings/secrets handling arrives in M0-5 / M0-10.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import Field

from personalai_contracts.schemas.base import StrictModel

_ENV_PREFIX = "PERSONALAI_"

# Maps an env var (without prefix) to a CoreConfig field.
_ENV_FIELDS = {
    "MODEL_PROVIDER": "model_provider",
    "RETRIEVER": "retriever",
    "VECTOR_REPOSITORY": "vector_repository",
    "OBJECT_STORE": "object_store",
    "BIND_HOST": "bind_host",
    "EGRESS_ENABLED": "egress_enabled",
}


class CoreConfig(StrictModel):
    """Selection of active adapters plus local-first runtime defaults."""

    model_provider: str = "ollama"
    retriever: str = "pgvector"
    vector_repository: str = "pgvector"
    object_store: str = "local"
    bind_host: str = Field(default="127.0.0.1", description="Loopback by default.")
    egress_enabled: bool = Field(default=False, description="Network egress off by default.")

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> CoreConfig:
        """Build config from ``PERSONALAI_*`` environment variables, falling back to defaults."""
        values: dict[str, object] = {}
        for env_key, field_name in _ENV_FIELDS.items():
            raw = environ.get(_ENV_PREFIX + env_key)
            if raw is None:
                continue
            if field_name == "egress_enabled":
                values[field_name] = raw.strip().lower() in {"1", "true", "yes", "on"}
            else:
                values[field_name] = raw
        return cls.model_validate(values)
