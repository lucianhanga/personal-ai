"""CoreConfig: local-first defaults and env-driven overrides."""

from __future__ import annotations

from personalai_contracts.schemas import TenantSettings
from personalai_core.config import CoreConfig, effective_config


def test_defaults_are_local_first() -> None:
    config = CoreConfig()
    assert config.bind_host == "127.0.0.1"
    assert config.egress_enabled is False
    # M8 graph is opt-in; single-agent loop by default.
    assert config.agent_graph_enabled is False
    assert config.agent_accuracy_mode == "standard"
    assert config.db_pool_max_size == 20 and config.agent_timeout_seconds == 300


def test_from_env_parses_agent_graph_flags() -> None:
    config = CoreConfig.from_env(
        {"PERSONALAI_AGENT_GRAPH_ENABLED": "true", "PERSONALAI_AGENT_ACCURACY_MODE": "accurate"}
    )
    assert config.agent_graph_enabled is True
    assert config.agent_accuracy_mode == "accurate"


def test_from_env_overrides_and_parses_bool() -> None:
    config = CoreConfig.from_env(
        {
            "PERSONALAI_MODEL_PROVIDER": "fake",
            "PERSONALAI_VECTOR_REPOSITORY": "memory",
            "PERSONALAI_EGRESS_ENABLED": "true",
            "UNRELATED": "ignored",
        }
    )
    assert config.model_provider == "fake"
    assert config.vector_repository == "memory"
    assert config.egress_enabled is True


def test_from_env_empty_uses_defaults() -> None:
    config = CoreConfig.from_env({})
    assert config.model_provider == "ollama"
    assert config.egress_enabled is False


def test_from_env_parses_port_and_origins() -> None:
    config = CoreConfig.from_env(
        {
            "PERSONALAI_BIND_PORT": "9000",
            "PERSONALAI_ALLOWED_ORIGINS": "http://a, http://b ,",
        }
    )
    assert config.bind_port == 9000
    assert config.allowed_origins == ("http://a", "http://b")


def test_effective_config_overlays_only_non_null_overrides() -> None:
    base = CoreConfig()
    overrides = TenantSettings(
        default_model="qwen3:14b",
        agent_graph_enabled=True,
        agent_max_iterations=12,
        grounding_enabled=False,
    )
    eff = effective_config(base, overrides)
    # Overridden fields take the tenant value...
    assert eff.default_model == "qwen3:14b"
    assert eff.agent_graph_enabled is True
    assert eff.agent_max_iterations == 12
    assert eff.grounding_enabled is False
    # ...while unset (None) fields inherit the base default.
    assert eff.ollama_host == base.ollama_host
    assert eff.memory_enabled == base.memory_enabled
    # Base is left untouched (immutable copy).
    assert base.default_model == CoreConfig().default_model


def test_effective_config_no_overrides_returns_base() -> None:
    base = CoreConfig()
    assert effective_config(base, TenantSettings()) is base
