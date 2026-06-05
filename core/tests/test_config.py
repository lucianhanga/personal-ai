"""CoreConfig: local-first defaults and env-driven overrides."""

from __future__ import annotations

from personalai_core.config import CoreConfig


def test_defaults_are_local_first() -> None:
    config = CoreConfig()
    assert config.bind_host == "127.0.0.1"
    assert config.egress_enabled is False


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
