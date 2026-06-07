"""Short-term memory (M4-1): keep a conversation within budget via a rolling summary.

Pure split helper + an async summarizer (uses a ModelProvider). The orchestrator keeps the last
``keep_recent`` messages verbatim and folds older ones into a running summary, scoped to one
conversation (short-term memory is isolated per chat).
"""

from __future__ import annotations

from collections.abc import Sequence

from personalai_contracts.ports import ChatMessage, GenerationRequest, ModelProvider, Role


def split_recent(
    messages: Sequence[ChatMessage], keep_recent: int
) -> tuple[list[ChatMessage], list[ChatMessage]]:
    """Return ``(older, recent)`` where ``recent`` is the last ``keep_recent`` messages."""
    if keep_recent < 0:
        raise ValueError("keep_recent must be >= 0")
    if len(messages) <= keep_recent:
        return [], list(messages)
    cut = len(messages) - keep_recent
    return list(messages[:cut]), list(messages[cut:])


async def summarize(
    provider: ModelProvider,
    model: str,
    prior_summary: str | None,
    to_fold: Sequence[ChatMessage],
) -> str:
    """Update a running summary by folding in earlier turns (``to_fold``)."""
    transcript = "\n".join(f"{m.role.value}: {m.content}" for m in to_fold)
    prior = f"Existing summary:\n{prior_summary}\n\n" if prior_summary else ""
    prompt = (
        "You maintain a concise running summary of a conversation so it stays within the model's "
        "context window. Update the summary to incorporate the new turns below, preserving durable "
        "facts, decisions, and open threads. Return only the updated summary.\n\n"
        f"{prior}New turns:\n{transcript}"
    )
    result = await provider.generate(
        GenerationRequest(messages=[ChatMessage(Role.USER, prompt)], model=model)
    )
    return result.text.strip()
