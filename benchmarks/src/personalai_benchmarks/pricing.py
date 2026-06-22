"""Approximate model prices for cost-adjusted leaderboards (#330).

USD per 1,000,000 tokens, as ``(input, output)``. **Hand-maintained snapshot — prices change often;
edit this table.** A model not listed shows "—" in the report rather than a guessed cost. PersonalAI
(local) is free. Keyed by the model id used in a contestant's name (`provider:model`).
"""

from __future__ import annotations

from collections.abc import Mapping

# (input $/1M, output $/1M). Approximate as of 2026-06 — verify against current pricing pages.
PRICES_USD_PER_1M: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    # Anthropic
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-6": (15.00, 75.00),
    "claude-opus-4-8": (15.00, 75.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    # DeepSeek
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    # Google
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 10.00),
    # xAI
    "grok-4.3": (3.00, 15.00),
    # Groq-hosted open models
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.3-70b-versatile": (0.59, 0.79),
}


def _model_of(system: str) -> str:
    """The model id from a contestant name like ``openai:gpt-4o`` or ``openai+tools:gpt-4o``."""
    return system.split(":", 1)[1] if ":" in system else system


def cost_usd(system: str, usage: Mapping[str, object]) -> float | None:
    """Cost of one run for ``system`` from its token ``usage``; 0 for local PersonalAI; None if the
    model has no price (shown as "—")."""
    if not system or system.startswith("personalia"):
        return 0.0  # local model: no API cost
    price = PRICES_USD_PER_1M.get(_model_of(system))
    if price is None:
        return None
    prompt = _as_int(usage.get("prompt_tokens"))
    completion = _as_int(usage.get("completion_tokens"))
    return (prompt * price[0] + completion * price[1]) / 1_000_000


def tokens_per_sec(usage: Mapping[str, object], latency_ms: float) -> float | None:
    """Output speed (completion tokens / second), or None if tokens/latency are unavailable."""
    completion = _as_int(usage.get("completion_tokens"))
    if completion <= 0 or latency_ms <= 0:
        return None
    return completion / (latency_ms / 1000.0)


def _as_int(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0
