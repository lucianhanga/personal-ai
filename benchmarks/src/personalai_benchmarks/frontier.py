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


@dataclass(frozen=True)
class Provider:
    """An OpenAI-compatible provider: where to call it, which env var holds its key, default model.

    ``default_model`` is a starting point only — model names change fast, so override per run with
    ``--models provider=model`` (CLI) rather than trusting these.
    """

    name: str
    base_url: str
    env_var: str
    default_model: str


# OpenAI-compatible endpoints. base_url is the prefix BEFORE "/chat/completions".
PROVIDERS: dict[str, Provider] = {
    "openai": Provider("openai", "https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4o"),
    "anthropic": Provider(
        "anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", "claude-3-5-sonnet-latest"
    ),
    "deepseek": Provider(
        "deepseek", "https://api.deepseek.com", "DEEPSEEK_API_KEY", "deepseek-chat"
    ),
    "xai": Provider("xai", "https://api.x.ai/v1", "XAI_API_KEY", "grok-2-latest"),
    "groq": Provider(
        "groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile"
    ),
    "gemini": Provider(
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
        "gemini-2.0-flash",
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

    def run(self, messages: Sequence[Mapping[str, str]], overrides: Mapping[str, Any]) -> RunResult:
        # Raw tier: no tools/memory; overrides are ignored except an explicit temperature.
        temperature = float(overrides.get("temperature", self._temperature))
        body = {"model": self.model, "messages": list(messages), "temperature": temperature}
        started = time.perf_counter()
        try:
            resp = self._client.post(
                f"{self.provider.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json=body,
            )
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


def missing_keys() -> list[str]:
    """Providers skipped because their API key is not set (for a clear 'skipped' report)."""
    return [p.name for p in PROVIDERS.values() if not os.environ.get(p.env_var)]
