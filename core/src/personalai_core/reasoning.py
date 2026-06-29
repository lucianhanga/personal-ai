"""Graded reasoning ("how much to think") levels, shared by the single-agent chat path and the
multi-agent graph so both apply one mechanism.

Benchmarked on qwen3.6:27b (arch qwen35): Ollama's think-level STRINGS ("low"/"medium"/"high") are
inert on Qwen3 — only gpt-oss has native effort tiers — so the depth gradient comes from a graded
system-prompt "reasoning budget" nudge, NOT the string. A level therefore maps to a boolean `think`
switch + an optional nudge. We deliberately impose no per-level output cap: a tight cap truncates
the reasoning mid-stream and starves the answer on hard problems, so the caller's existing output
ceiling and turn timeout bound worst-case latency instead.
"""

from __future__ import annotations

# The user-facing levels, in increasing thinking budget.
REASONING_LEVELS: tuple[str, ...] = ("off", "low", "medium", "high")

# Per-level system-prompt nudge (the real depth lever on Qwen3). "off" has no nudge.
_NUDGES: dict[str, str] = {
    "low": (
        "/think Think very briefly — at most a couple of short reasoning steps — then answer. "
        "Do not over-deliberate."
    ),
    "medium": "/think Think step by step but stay concise, then give the answer.",
    "high": (
        "/think Think thoroughly: explore alternative approaches, check edge cases, and verify "
        "your own reasoning before answering."
    ),
}


def resolve_reasoning(level: str | None) -> tuple[bool | None, str | None]:
    """Map a reasoning level to ``(think, nudge_text)``.

    - ``off`` -> ``(False, None)`` (thinking disabled, no nudge)
    - ``low``/``medium``/``high`` -> ``(True, nudge)``
    - ``None`` or unknown -> ``(None, None)`` meaning "no opinion": caller keeps its own default.
    """
    if level is None:
        return None, None
    if level == "off":
        return False, None
    return True, _NUDGES.get(level)
