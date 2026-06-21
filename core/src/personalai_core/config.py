"""Core configuration: which adapters are active, and runtime safety defaults.

Config-driven selection (ADR-0001): the composition root reads :class:`CoreConfig` and resolves
the active singleton adapters from the registries. Security defaults are local-first: bind to
loopback, keep network egress disabled, and only accept requests from allow-listed browser
origins unless explicitly widened (ADR / THREAT-MODEL). Proper secrets handling arrives in M0-10.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import Field

from personalai_contracts.schemas import TenantSettings
from personalai_contracts.schemas.base import StrictModel

_ENV_PREFIX = "PERSONALAI_"

# Maps an env var (without prefix) to a CoreConfig field.
_ENV_FIELDS = {
    "APP_MODE": "app_mode",
    "MODEL_PROVIDER": "model_provider",
    "DEFAULT_MODEL": "default_model",
    "OLLAMA_HOST": "ollama_host",
    "OLLAMA_NUM_CTX": "ollama_num_ctx",
    "OLLAMA_KEEP_ALIVE": "ollama_keep_alive",
    "MCP_CONFIG": "mcp_config_path",
    "AGENT_MAX_ITERATIONS": "agent_max_iterations",
    "AGENT_TIMEOUT_SECONDS": "agent_timeout_seconds",
    "AGENT_MODE": "agent_mode",
    "AGENT_GRAPH_ENABLED": "agent_graph_enabled",
    "AGENT_HUMAN_GATE": "agent_human_gate",
    "AGENT_ACCURACY_MODE": "agent_accuracy_mode",
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
    "TRANSCRIBE_ENABLED": "transcribe_enabled",
    "TRANSCRIBE_MODEL": "transcribe_model",
    "TRANSCRIBE_BASE_URL": "transcribe_base_url",
    "TRANSCRIBE_API_KEY": "transcribe_api_key",  # pragma: allowlist secret  (env var name)
    "DATABASE_URL": "database_url",
    "DB_POOL_MAX_SIZE": "db_pool_max_size",
    "EMBED_PROVIDER": "embed_provider",
    "EMBED_MODEL": "embed_model",
    "MAX_UPLOAD_BYTES": "max_upload_bytes",
    "MAX_REQUEST_BYTES": "max_request_bytes",
    "STM_KEEP_RECENT": "stm_keep_recent",
    "STM_SUMMARIZE": "stm_summarize",
    "MEMORY_ENABLED": "memory_enabled",
    "MEMORY_TOP_K": "memory_top_k",
    "GROUNDING_ENABLED": "grounding_enabled",
    "AUDIT_LOG_PATH": "audit_log_path",
    "SESSION_IDLE_SECONDS": "session_idle_seconds",
    "SESSION_ABSOLUTE_SECONDS": "session_absolute_seconds",
}

_INT_FIELDS = {
    "bind_port",
    "max_upload_bytes",
    "max_request_bytes",
    "db_pool_max_size",
    "stm_keep_recent",
    "memory_top_k",
    "ollama_num_ctx",
    "agent_max_iterations",
    "agent_timeout_seconds",
    "session_idle_seconds",
    "session_absolute_seconds",
}
_BOOL_FIELDS = {
    "egress_enabled",
    "stm_summarize",
    "memory_enabled",
    "egress_allow_any",
    "grounding_enabled",
    "agent_graph_enabled",
    "agent_human_gate",
    "transcribe_enabled",
}

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

    # Deployment mode (ADR-0010): "local" = single-user dev/personal (dev-login, stdio MCP ok);
    # "hosted" = multi-tenant SaaS (real login required, cookies+CSRF, remote-HTTP MCP only).
    app_mode: str = "local"
    model_provider: str = "ollama"
    default_model: str = "qwen3.6:35b-a3b"
    ollama_host: str = "http://127.0.0.1:11434"
    # Bound the Ollama context window (KV cache) to control memory / avoid swap on constrained RAM.
    ollama_num_ctx: int = 32768
    # How long Ollama keeps the model resident after a request ("30m", "1h", "-1" = never unload).
    # Keeps a large model warm between turns so it isn't cold-reloaded (slow on big models).
    ollama_keep_alive: str = "30m"
    # Path to an mcp.json (mcpServers map) of MCP servers to connect at startup (M7); empty = none.
    mcp_config_path: str = ""
    # Max model<->tool iterations in the agent loop before it must answer (multi-step tool use).
    agent_max_iterations: int = 8
    # Hard wall-clock cap on a whole chat turn (seconds). A wedged model/node can't hang the turn
    # forever; on expiry the stream emits E_TIMEOUT. Generous default for big local models.
    agent_timeout_seconds: int = 300
    # M8 (ADR-0011): opt into the multi-agent typed graph (planner/researcher/critic/verifier);
    # default off keeps the single-agent loop. accuracy_mode drives the verification-ladder depth
    # ("standard"/"accurate"). Security gates (approval, egress, tenant) are NEVER accuracy-gated.
    agent_graph_enabled: bool = False
    # Agentic mode (#290): "single" = single-agent loop, "multi" = the planner/researcher/critic
    # graph, "custom" = user-defined agents (reserved/future). The user-facing control; the chat
    # path drives graph selection off this. agent_graph_enabled stays as the legacy env flag
    # (from_env upgrades the mode to "multi" when it is set and no mode is given).
    agent_mode: str = "single"
    # M8.1c (ADR-0012): when the graph is enabled, also suspend each turn at a durable human gate
    # (after the critic) for approve/reject before finalizing. Requires the graph; default off so
    # the normal flow finalizes without a gate. The checkpoint is tenant-scoped (RLS) via TenantDb.
    agent_human_gate: bool = False
    agent_accuracy_mode: str = "standard"
    retriever: str = "pgvector"
    vector_repository: str = "pgvector"
    object_store: str = "local"
    # Dev default: local pgvector via docker-compose (trust auth, no password in code).
    database_url: str = "postgresql://personalai@127.0.0.1:5432/personalai"
    # asyncpg pool max size. A turn fans out into per-node RLS-bound queries (each a short
    # transaction) concurrent with streaming + background memory, and M8 multiplies that — so the
    # default is generous to avoid pool-exhaustion stalls.
    db_pool_max_size: int = 20
    embed_provider: str = "ollama"
    embed_model: str = "qwen3-embedding:0.6b"
    max_upload_bytes: int = 10_000_000
    # Hard ceiling on any request body (DoS guard); exceeds max_upload_bytes + multipart overhead.
    max_request_bytes: int = 12_000_000
    # Short-term memory: keep the last N messages verbatim; fold older turns into a rolling summary.
    stm_keep_recent: int = 10
    stm_summarize: bool = True
    # Long-term memory: extract durable facts after a turn (skipped for incognito conversations).
    memory_enabled: bool = True
    memory_top_k: int = 5
    # Inject a grounding/anti-hallucination system prompt (ground in context/tools; admit doubt).
    grounding_enabled: bool = True
    # Append-only JSONL audit sink path (survives restart); empty = in-memory only.
    audit_log_path: str = ""
    # Session lifetimes (ADR-0010): sliding idle window + hard absolute cap, in seconds.
    session_idle_seconds: int = 86_400  # 24h
    session_absolute_seconds: int = 604_800  # 7d
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
    # Speech-to-text (M9.2): opt-in voice input via an OpenAI-compatible /audio/transcriptions
    # endpoint (OpenAI or a local whisper server). Off by default; a local server on loopback works
    # with egress disabled. Empty base/key fall back to the OpenAI provider's base/key.
    transcribe_enabled: bool = Field(default=False, description="Enable speech-to-text input.")
    transcribe_model: str = Field(default="whisper-1", description="Transcription model name.")
    transcribe_base_url: str = Field(
        default="", description="Transcription endpoint base URL; empty = use openai_base_url."
    )
    transcribe_api_key: str | None = Field(
        default=None, description="Transcription API key (secret); empty = use openai_api_key."
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
        # Back-compat (#290): the legacy AGENT_GRAPH_ENABLED flag maps to agent_mode="multi" when no
        # explicit AGENT_MODE is given, so existing env config keeps selecting the graph.
        if "agent_mode" not in values and values.get("agent_graph_enabled") is True:
            values["agent_mode"] = "multi"
        return cls.model_validate(values)


def effective_config(base: CoreConfig, overrides: TenantSettings) -> CoreConfig:
    """Overlay a tenant's non-null preference overrides (#289) onto the boot-time ``base`` config.

    ``TenantSettings`` field names match ``CoreConfig`` exactly, and a ``None`` override means
    "inherit the deployment default", so the overlay is a plain copy of the non-null values. Returns
    ``base`` unchanged when there is nothing to override (the common no-saved-settings case)."""
    update = overrides.model_dump(exclude_none=True)
    if not update:
        return base
    return base.model_copy(update=update)
