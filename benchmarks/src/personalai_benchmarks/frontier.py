"""Frontier-model contestants via one OpenAI-compatible client (M-Bench Phase 2, #322).

Grok, Groq, DeepSeek, OpenAI, Anthropic, and Gemini all expose an OpenAI-compatible
``/chat/completions`` endpoint, so a single adapter — parameterized by (base_url, api_key, model) —
covers them all. A provider whose API key is absent from the environment is skipped (``build``
returns None), so a run degrades gracefully to whatever keys are present. This is the *raw* tier (no
tools/memory); the tool-equipped wrapper and PersonalAI-on-a-frontier-model are separate pieces.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from personalai_benchmarks.adapters import RunResult

# Capability/cost tiers a provider's models are tagged with. "medium"/"best" may have 2 models each
# (a current + an older one) so the leaderboard shows the full cheapest→best spread per provider.
MODEL_TIERS = ("cheapest", "medium", "best")


@dataclass(frozen=True)
class Model:
    """One model id tagged with its cost/quality ``tier`` (∈ :data:`MODEL_TIERS`)."""

    id: str
    tier: str


@dataclass(frozen=True)
class Provider:
    """An OpenAI-compatible provider: where to call it, its key env var, and a tagged model lineup.

    Model ids are validated against each provider's live ``/models`` but change fast — override per
    run with ``--models provider=model`` (CLI) rather than trusting these.
    """

    name: str
    base_url: str
    env_var: str
    models: tuple[Model, ...]

    @property
    def default_model(self) -> str:
        """A single representative (the first ``medium``, else the first model) — back-compat for
        runs that don't sweep a whole tier."""
        return next((m.id for m in self.models if m.tier == "medium"), self.models[0].id)

    def tier(self, tier: str) -> list[str]:
        """Model ids in ``tier`` (or every id when ``tier == 'all'``)."""
        return [m.id for m in self.models if tier == "all" or m.tier == tier]


def _p(name: str, base_url: str, env_var: str, lineup: tuple[tuple[str, str], ...]) -> Provider:
    return Provider(name, base_url, env_var, tuple(Model(mid, tier) for mid, tier in lineup))


# OpenAI-compatible endpoints (base_url is the prefix BEFORE "/chat/completions"). Each provider's
# lineup spans cheapest → best, validated against its /models on 2026-06; older ids fill the gaps.
# DeepSeek exposes only 2 models and xAI only 4, so they aren't padded. Some reasoning flagships
# (OpenAI GPT-5.x, xAI grok-4.x reasoning, DeepSeek v4-pro) reject a custom `temperature`; the
# adapter retries without it on a 400. Prices live in pricing.py.
PROVIDERS: dict[str, Provider] = {
    "openai": _p(
        "openai",
        "https://api.openai.com/v1",
        "OPENAI_API_KEY",
        (
            ("gpt-5.4-nano", "cheapest"),
            ("gpt-5.4-mini", "medium"),
            ("gpt-4o", "medium"),
            ("gpt-5.5", "best"),
            ("gpt-4.1", "best"),
        ),
    ),
    "anthropic": _p(
        "anthropic",
        "https://api.anthropic.com/v1",
        "ANTHROPIC_API_KEY",
        (
            ("claude-haiku-4-5-20251001", "cheapest"),
            ("claude-sonnet-4-6", "medium"),
            ("claude-sonnet-4-5-20250929", "medium"),
            ("claude-opus-4-8", "best"),
            ("claude-opus-4-6", "best"),
        ),
    ),
    "deepseek": _p(
        "deepseek",
        "https://api.deepseek.com",
        "DEEPSEEK_API_KEY",
        (("deepseek-v4-flash", "cheapest"), ("deepseek-v4-pro", "best")),
    ),
    "xai": _p(
        "xai",
        "https://api.x.ai/v1",
        "XAI_API_KEY",
        (
            ("grok-4.20-0309-non-reasoning", "cheapest"),
            ("grok-4.20-0309-reasoning", "medium"),
            ("grok-4.20-multi-agent-0309", "medium"),
            ("grok-4.3", "best"),
        ),
    ),
    "groq": _p(
        "groq",
        "https://api.groq.com/openai/v1",
        "GROQ_API_KEY",
        (
            ("llama-3.1-8b-instant", "cheapest"),
            ("llama-3.3-70b-versatile", "medium"),
            ("openai/gpt-oss-20b", "medium"),
            ("openai/gpt-oss-120b", "best"),
            ("qwen/qwen3-32b", "best"),
        ),
    ),
    "gemini": _p(
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
        (
            ("gemini-2.5-flash-lite", "cheapest"),
            ("gemini-2.5-flash", "medium"),
            ("gemini-2.0-flash", "medium"),
            ("gemini-3.5-flash", "best"),
            ("gemini-2.5-pro", "best"),
        ),
    ),
}


class OpenAICompatAdapter:
    """A raw-LLM :class:`SystemUnderTest` over an OpenAI-compatible ``/chat/completions`` route."""

    def __init__(
        self,
        provider: Provider,
        api_key: str,
        model: str,
        *,
        temperature: float = 0.0,
        client: httpx.Client | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.provider = provider
        self.model = model
        self.name = f"{provider.name}:{model}"
        self._key = api_key
        self._temperature = temperature
        self._client = client or httpx.Client(timeout=timeout)

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        return self._client.post(
            f"{self.provider.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._key}"},
            json=body,
        )

    def run(self, messages: Sequence[Mapping[str, str]], overrides: Mapping[str, Any]) -> RunResult:
        # Raw tier: no tools/memory; overrides are ignored except an explicit temperature.
        temperature = float(overrides.get("temperature", self._temperature))
        body: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": temperature,
        }
        started = time.perf_counter()
        try:
            resp = self._post(body)
            # Some newer models (e.g. reasoning models) reject `temperature` — retry without it.
            if resp.status_code == 400 and "temperature" in resp.text.lower():
                body.pop("temperature", None)
                resp = self._post(body)
        except httpx.HTTPError as exc:
            return RunResult(error=f"{self.provider.name} request failed: {exc}")
        latency_ms = (time.perf_counter() - started) * 1000.0
        if resp.status_code != 200:
            return RunResult(
                error=f"{self.provider.name} HTTP {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        try:
            answer = str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            return RunResult(error=f"{self.provider.name} unexpected response: {exc}")
        usage = data.get("usage") or {}
        return RunResult(
            answer=answer,
            latency_ms=round(latency_ms, 1),
            usage=dict(usage) if isinstance(usage, dict) else {},
            config_used={"provider": self.provider.name, "model": self.model, "tier": "raw"},
        )


def build(
    provider_name: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> OpenAICompatAdapter | None:
    """An adapter for ``provider_name``, or None if its API key is absent (so the run skips it)."""
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise KeyError(f"unknown provider {provider_name!r}; known: {', '.join(PROVIDERS)}")
    key = api_key if api_key is not None else os.environ.get(provider.env_var)
    if not key:
        return None
    return OpenAICompatAdapter(provider, key, model or provider.default_model, client=client)


def available(
    *, models: Mapping[str, str] | None = None, client: httpx.Client | None = None
) -> list[OpenAICompatAdapter]:
    """Adapters for every provider whose key is set (others are skipped). ``models`` overrides the
    default model per provider name."""
    models = models or {}
    out: list[OpenAICompatAdapter] = []
    for name in PROVIDERS:
        adapter = build(name, model=models.get(name), client=client)
        if adapter is not None:
            out.append(adapter)
    return out


def build_tier(
    provider_name: str, tier: str, *, client: httpx.Client | None = None
) -> list[OpenAICompatAdapter]:
    """Adapters for every model in ``provider_name``'s ``tier`` (``'all'`` = the full lineup); empty
    if the provider's key is absent. A provider with no models in ``tier`` yields nothing."""
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise KeyError(f"unknown provider {provider_name!r}; known: {', '.join(PROVIDERS)}")
    out: list[OpenAICompatAdapter] = []
    for model in provider.tier(tier):
        adapter = build(provider_name, model=model, client=client)
        if adapter is not None:
            out.append(adapter)
    return out


def available_tier(
    tier: str, *, providers: list[str] | None = None, client: httpx.Client | None = None
) -> list[OpenAICompatAdapter]:
    """Tier adapters across ``providers`` (default: all known); key-absent providers are skipped."""
    names = providers if providers is not None else list(PROVIDERS)
    return [a for name in names for a in build_tier(name, tier, client=client)]


def missing_keys() -> list[str]:
    """Providers skipped because their API key is not set (for a clear 'skipped' report)."""
    return [p.name for p in PROVIDERS.values() if not os.environ.get(p.env_var)]
