"""Long-term memory formation (M4-2): extract durable facts from a turn, then store them.

Write path only (retrieval/injection is M4-3). Extraction uses structured output; storage dedups
near-identical memories. Depends only on contracts ports/schemas — testable with fakes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from personalai_contracts.ports import (
    ChatMessage,
    GenerationRequest,
    MemoryItem,
    MemoryKind,
    MemoryStore,
    ModelProvider,
    Role,
)
from personalai_contracts.schemas.memory import ExtractedFact, ExtractionResult
from personalai_core.memory_consolidation import consolidate_fact


async def recall(
    *,
    query: str,
    embed_provider: ModelProvider,
    embed_model: str,
    store: MemoryStore,
    top_k: int = 5,
) -> list[MemoryItem]:
    """Return the memories most relevant to ``query`` (empty if nothing embeds/matches)."""
    embeddings = await embed_provider.embed([query], embed_model)
    if not embeddings.vectors:
        return []
    return list(await store.search(embeddings.vectors[0], top_k))


_PROMPT = (
    "Extract durable, user-relevant long-term memories from the conversation excerpt below. "
    "Only include things worth remembering across future chats — stable facts about the user, "
    "their projects/files, and their preferences. Ignore small talk, transient details, and "
    "anything already obvious. Return JSON matching the schema; use an empty list if there is "
    "nothing worth remembering.\n\nConversation:\n"
)


async def extract_facts(
    provider: ModelProvider,
    model: str,
    messages: Sequence[ChatMessage],
    *,
    min_confidence: float = 0.5,
) -> list[ExtractedFact]:
    """Extract candidate memories from ``messages`` via structured output."""
    transcript = "\n".join(f"{m.role.value}: {m.content}" for m in messages)
    request = GenerationRequest(
        messages=[ChatMessage(Role.USER, _PROMPT + transcript)],
        model=model,
        json_schema=ExtractionResult.model_json_schema(),
        # Extraction is a JSON task — never reason (faster, and keeps the output clean JSON).
        think=False,
    )
    result = await provider.generate(request)
    try:
        parsed = ExtractionResult.model_validate(json.loads(result.text))
    except (ValueError, TypeError):
        return []  # fail closed: invalid/non-JSON output stores nothing
    return [f for f in parsed.facts if f.text.strip() and f.confidence >= min_confidence]


async def remember(
    *,
    messages: Sequence[ChatMessage],
    gen_provider: ModelProvider,
    gen_model: str,
    embed_provider: ModelProvider,
    embed_model: str,
    store: MemoryStore,
    source: Mapping[str, str],
    min_confidence: float = 0.5,
) -> list[MemoryItem]:
    """Extract facts and consolidate each into long-term memory (dedup + conflicts, #310)."""
    facts = await extract_facts(gen_provider, gen_model, messages, min_confidence=min_confidence)
    stored: list[MemoryItem] = []
    for fact in facts:
        try:
            outcome = await consolidate_fact(
                text=fact.text,
                kind=MemoryKind(fact.kind),
                confidence=fact.confidence,
                source=source,
                store=store,
                embed_provider=embed_provider,
                embed_model=embed_model,
                judge_provider=gen_provider,
                judge_model=gen_model,
            )
        except ValueError:
            continue  # could not embed this fact; skip (memory is best-effort)
        if outcome.item is not None:
            stored.append(outcome.item)
    return stored
