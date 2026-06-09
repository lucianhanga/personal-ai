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
    "DEFAULT_MODEL": "default_model",
    "OLLAMA_HOST": "ollama_host",
    "OLLAMA_NUM_CTX": "ollama_num_ctx",
    "MCP_CONFIG": "mcp_config_path",
    "RETRIEVER": "retriever",
    "VECTOR_REPOSITORY": "vector_repository",
    "OBJECT_STORE": "object_store",
    "BIND_HOST": "bind_host",
    "BIND_PORT": "bind_port",
    "EGRESS_ENABLED": "egress_enabled",
    "ALLOWED_EGRESS_HOSTS": "allowed_egress_hosts",
    "EGRESS_ALLOW_ANY": "egress_allow_any",
    "AUTH_TOKEN": "auth_token",
    "ALLOWED_ORIGINS": "allowed_origins",
    "OPENAI_API_KEY": "openai_api_key",  # pragma: allowlist secret  (env var name, not a secret)
    "OPENAI_BASE_URL": "openai_base_url",
    "DATABASE_URL": "database_url",
    "EMBED_PROVIDER": "embed_provider",
    "EMBED_MODEL": "embed_model",
    "MAX_UPLOAD_BYTES": "max_upload_bytes",
    "STM_KEEP_RECENT": "stm_keep_recent",
    "STM_SUMMARIZE": "stm_summarize",
    "MEMORY_ENABLED": "memory_enabled",
    "MEMORY_TOP_K": "memory_top_k",
}

_INT_FIELDS = {"bind_port", "max_upload_bytes", "stm_keep_recent", "memory_top_k", "ollama_num_ctx"}
_BOOL_FIELDS = {"egress_enabled", "stm_summarize", "memory_enabled", "egress_allow_any"}

_CSV_FIELDS = {"allowed_origins", "allowed_egress_hosts"}

_TRUTHY = {"1", "true", "yes", "on"}
_DEFAULT_ORIGINS = (
    "http://127.0.0.1",
    "http://localhost",
    # Vite dev (5173) and preview (4173) servers, loopback only — for local UI development.
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
)


class CoreConfig(StrictModel):
    """Selection of active adapters plus local-first runtime defaults."""

    model_provider: str = "ollama"
    default_model: str = "qwen3.6:35b-a3b"
    ollama_host: str = "http://127.0.0.1:11434"
    # Bound the Ollama context window (KV cache) to control memory / avoid swap on constrained RAM.
    ollama_num_ctx: int = 32768
    # Path to an mcp.json (mcpServers map) of MCP servers to connect at startup (M7); empty = none.
    mcp_config_path: str = ""
    retriever: str = "pgvector"
    vector_repository: str = "pgvector"
    object_store: str = "local"
    # Dev default: local pgvector via docker-compose (trust auth, no password in code).
    database_url: str = "postgresql://personalai@127.0.0.1:5432/personalai"
    embed_provider: str = "ollama"
    embed_model: str = "mxbai-embed-large"
    max_upload_bytes: int = 10_000_000
    # Short-term memory: keep the last N messages verbatim; fold older turns into a rolling summary.
    stm_keep_recent: int = 10
    stm_summarize: bool = True
    # Long-term memory: extract durable facts after a turn (skipped for incognito conversations).
    memory_enabled: bool = True
    memory_top_k: int = 5
    bind_host: str = Field(default="127.0.0.1", description="Loopback by default.")
    bind_port: int = Field(default=8765, ge=1, le=65535)
    egress_enabled: bool = Field(default=False, description="Network egress off by default.")
    allowed_egress_hosts: tuple[str, ...] = Field(
        default=(),
        description="When egress is enabled, the hosts allowed. Empty = fail-closed (deny all).",
    )
    egress_allow_any: bool = Field(
        default=False,
        description="Explicit opt-in to allow ANY host when egress is enabled with no allowlist.",
    )
    auth_token: str | None = Field(
        default=None, description="Bearer token required by protected routes; set via env."
    )
    allowed_origins: tuple[str, ...] = Field(
        default=_DEFAULT_ORIGINS, description="Browser origins permitted to call the API."
    )
    openai_api_key: str | None = Field(
        default=None, description="API key for the OpenAI-compatible remote provider (secret)."
    )
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="Base URL for the OpenAI-compatible remote provider.",
    )

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> CoreConfig:
        """Build config from ``PERSONALAI_*`` environment variables, falling back to defaults."""
        values: dict[str, object] = {}
        for env_key, field_name in _ENV_FIELDS.items():
            raw = environ.get(_ENV_PREFIX + env_key)
            if raw is None:
                continue
            if field_name in _BOOL_FIELDS:
                values[field_name] = raw.strip().lower() in _TRUTHY
            elif field_name in _INT_FIELDS:
                values[field_name] = int(raw)
            elif field_name in _CSV_FIELDS:
                values[field_name] = tuple(o.strip() for o in raw.split(",") if o.strip())
            else:
                values[field_name] = raw
        return cls.model_validate(values)
