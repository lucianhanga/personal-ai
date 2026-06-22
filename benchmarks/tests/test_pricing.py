"""Pricing math: cost from token usage, output speed, unpriced/local handling (#330)."""

from __future__ import annotations

from personalai_benchmarks import pricing


def test_cost_from_usage_for_a_priced_model() -> None:
    pricing.PRICES_USD_PER_1M["test-model"] = (2.0, 10.0)  # $/1M (in, out)
    cost = pricing.cost_usd("openai:test-model", {"prompt_tokens": 1000, "completion_tokens": 500})
    # 1000*2/1e6 + 500*10/1e6 = 0.002 + 0.005
    assert cost is not None and abs(cost - 0.007) < 1e-9


def test_unpriced_model_is_none() -> None:
    assert pricing.cost_usd("xai:some-unknown-model", {"completion_tokens": 100}) is None


def test_local_personalai_is_free() -> None:
    assert pricing.cost_usd("personalia", {"completion_tokens": 9999}) == 0.0


def test_tokens_per_sec() -> None:
    assert pricing.tokens_per_sec({"completion_tokens": 500}, 1000.0) == 500.0  # 500 tok / 1s
    assert pricing.tokens_per_sec({"completion_tokens": 0}, 1000.0) is None
    assert pricing.tokens_per_sec({"completion_tokens": 50}, 0.0) is None
