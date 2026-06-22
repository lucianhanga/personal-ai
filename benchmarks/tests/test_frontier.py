"""Frontier adapter: OpenAI-compatible call, graceful skip on missing keys (no network) (#322)."""

from __future__ import annotations

import httpx
import pytest
from personalai_benchmarks.frontier import (
    MODEL_TIERS,
    PROVIDERS,
    OpenAICompatAdapter,
    available,
    build,
    build_tier,
    missing_keys,
)


def _client(handler) -> httpx.Client:  # type: ignore[no-untyped-def]
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_handler(request: httpx.Request) -> httpx.Response:
    # Echo back a fixed answer + usage, in OpenAI chat-completions shape.
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "the answer is 42"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


def test_calls_openai_compatible_endpoint_and_normalizes() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        import json as _json

        seen["model"] = _json.loads(request.content)["model"]
        return _ok_handler(request)

    adapter = build("deepseek", model="deepseek-chat", api_key="sk-test", client=_client(handler))
    assert adapter is not None and adapter.name == "deepseek:deepseek-chat"
    result = adapter.run([{"role": "user", "content": "what is the answer?"}], {})
    assert result.error is None
    assert result.answer == "the answer is 42"
    assert result.usage["total_tokens"] == 15
    assert result.config_used == {"provider": "deepseek", "model": "deepseek-chat", "tier": "raw"}
    assert seen["url"] == "https://api.deepseek.com/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["model"] == "deepseek-chat"


def test_build_returns_none_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert build("xai") is None  # no key -> skipped, not an error


def test_unknown_provider_raises() -> None:
    with pytest.raises(KeyError, match="unknown provider"):
        build("not-a-provider")


def test_http_error_is_captured_not_raised() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    adapter = build("openai", api_key="bad", client=_client(boom))
    assert adapter is not None
    result = adapter.run([{"role": "user", "content": "hi"}], {})
    assert result.error is not None and "401" in result.error


def test_available_includes_only_providers_with_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for p in PROVIDERS.values():
        monkeypatch.delenv(p.env_var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-x")
    names = {a.provider.name for a in available(client=_client(_ok_handler))}
    assert names == {"openai", "groq"}
    assert set(missing_keys()) >= {"anthropic", "deepseek", "xai", "gemini"}


def test_every_provider_has_a_valid_tagged_lineup() -> None:
    for p in PROVIDERS.values():
        assert p.models, f"{p.name} has no models"
        tiers = {m.tier for m in p.models}
        assert tiers <= set(MODEL_TIERS), f"{p.name} has an unknown tier: {tiers}"
        assert "cheapest" in tiers, f"{p.name} has no cheapest model"
        # default_model resolves to a real id in the lineup (back-compat for single-model runs).
        assert p.default_model in {m.id for m in p.models}


def test_provider_tier_selects_the_right_models() -> None:
    openai = PROVIDERS["openai"]
    assert openai.tier("best") == ["gpt-5.5", "gpt-4.1"]  # 2 best models
    assert openai.tier("cheapest") == ["gpt-5.4-nano"]
    assert openai.tier("all") == [m.id for m in openai.models]  # everything, in order
    # DeepSeek is genuinely 2-tier — no medium, not padded.
    assert PROVIDERS["deepseek"].tier("medium") == []


def test_build_tier_builds_an_adapter_per_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    adapters = build_tier("openai", "best", client=_client(_ok_handler))
    assert [a.model for a in adapters] == ["gpt-5.5", "gpt-4.1"]
    assert build_tier("openai", "all", client=_client(_ok_handler)) != []  # full lineup


def test_build_tier_skips_a_provider_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert build_tier("xai", "best", client=_client(_ok_handler)) == []


def test_temperature_override_is_sent() -> None:
    sent: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        sent["temperature"] = _json.loads(request.content)["temperature"]
        return _ok_handler(request)

    adapter = OpenAICompatAdapter(
        PROVIDERS["groq"], "gsk", "llama-3.3-70b-versatile", client=_client(handler)
    )
    adapter.run([{"role": "user", "content": "hi"}], {"temperature": 0.7})
    assert sent["temperature"] == 0.7
