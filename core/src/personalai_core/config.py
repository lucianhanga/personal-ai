"""Core configuration: which adapters are active, and runtime safety defaults.

Config-driven selection (ADR-0001): the composition root reads :class:`CoreConfig` and resolves
the active singleton adapters from the registries. Security defaults are local-first: bind to
loopback, keep network egress disabled, and only accept requests from allow-listed browser
origins unless explicitly widened (ADR / THREAT-MODEL). Proper secrets handling arrives in M0-10.
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
    "BIND_PORT": "bind_port",
    "EGRESS_ENABLED": "egress_enabled",
    "AUTH_TOKEN": "auth_token",
    "ALLOWED_ORIGINS": "allowed_origins",
}

_TRUTHY = {"1", "true", "yes", "on"}
_DEFAULT_ORIGINS = ("http://127.0.0.1", "http://localhost")


class CoreConfig(StrictModel):
    """Selection of active adapters plus local-first runtime defaults."""

    model_provider: str = "ollama"
    retriever: str = "pgvector"
    vector_repository: str = "pgvector"
    object_store: str = "local"
    bind_host: str = Field(default="127.0.0.1", description="Loopback by default.")
    bind_port: int = Field(default=8765, ge=1, le=65535)
    egress_enabled: bool = Field(default=False, description="Network egress off by default.")
    auth_token: str | None = Field(
        default=None, description="Bearer token required by protected routes; set via env."
    )
    allowed_origins: tuple[str, ...] = Field(
        default=_DEFAULT_ORIGINS, description="Browser origins permitted to call the API."
    )

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> CoreConfig:
        """Build config from ``PERSONALAI_*`` environment variables, falling back to defaults."""
        values: dict[str, object] = {}
        for env_key, field_name in _ENV_FIELDS.items():
            raw = environ.get(_ENV_PREFIX + env_key)
            if raw is None:
                continue
            if field_name == "egress_enabled":
                values[field_name] = raw.strip().lower() in _TRUTHY
            elif field_name == "bind_port":
                values[field_name] = int(raw)
            elif field_name == "allowed_origins":
                values[field_name] = tuple(o.strip() for o in raw.split(",") if o.strip())
            else:
                values[field_name] = raw
        return cls.model_validate(values)
