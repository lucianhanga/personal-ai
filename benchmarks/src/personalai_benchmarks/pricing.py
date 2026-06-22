"""Approximate model prices for cost-adjusted leaderboards (#330).

USD per 1,000,000 tokens, as ``(input, output)``. **Hand-maintained snapshot — prices change often;
edit this table.** A model not listed shows "—" in the report rather than a guessed cost. PersonalAI
(local) is free. Keyed by the model id used in a contestant's name (`provider:model`).
"""

from __future__ import annotations

from collections.abc import Mapping

# (input $/1M, output $/1M). Approximate as of 2026-06 — verify against current pricing pages.
# A model absent here renders "—" in the report (no guessed cost), so it's fine to omit any whose
# price we couldn't confirm (e.g. xAI grok-4.20, Groq gpt-oss). "# verify" = lower confidence.
PRICES_USD_PER_1M: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-5.5": (5.00, 30.00),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-mini": (0.40, 1.60),
    # Anthropic
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-6": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    # DeepSeek
    "deepseek-v4-flash": (0.14, 0.28),
    "deepseek-v4-pro": (0.44, 0.87),  # verify: promotional rate
    # Google
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.0-flash": (0.10, 0.40),
    # xAI (the grok-4.20 line is unpriced -> renders "—")
    "grok-4.3": (1.25, 2.50),  # verify
    # Groq-hosted open models
    "openai/gpt-oss-120b": (0.15, 0.75),  # verify
    "openai/gpt-oss-20b": (0.10, 0.50),  # verify
    "qwen/qwen3-32b": (0.29, 0.59),  # verify
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
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
