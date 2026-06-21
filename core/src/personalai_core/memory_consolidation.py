"""Memory consolidation (#310): decide ADD / UPDATE / NOOP for a candidate fact.

Both write paths — the explicit `remember` tool (hot path) and the background extractor — route a
new fact through :func:`consolidate_fact` so dedup and conflict handling are identical and a fact is
never blindly appended. A near-duplicate is dropped (NOOP); a fact that contradicts an existing one
supersedes it and stores the correction (UPDATE); anything else is added (ADD). The decision uses a
schema-constrained LLM judge (:func:`generate_structured`) and fails closed to dedup-only behaviour
if the judge is unavailable, so it never regresses. Depends only on contracts ports.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from personalai_contracts.ports import (
    ChatMessage,
    MemoryItem,
    MemoryKind,
    MemoryStore,
    ModelProvider,
    Role,
)
from personalai_core.structured import generate_structured

# Cosine-similarity gates. A candidate at/above DEDUP is a near-duplicate in the fallback path;
# anything at/above RELATE is "related enough" to ask the judge about (below it, just add).
DEDUP_THRESHOLD = 0.92
RELATE_THRESHOLD = 0.6

Op = Literal["add", "update", "noop"]


class _Decision(BaseModel):
    """The judge's verdict on a candidate fact versus the related existing memories."""

    # Strict: an unrelated JSON object (e.g. an extraction result) must not validate as a decision,
    # so the judge falls back to dedup-only rather than silently mis-acting.
    model_config = ConfigDict(extra="forbid")

    op: Op = "add"
    # For "update": the id (from the provided list) of the memory the new fact replaces.
    target_id: str | None = None
    # For "update": the corrected/merged statement to store in place of the old one.
    text: str | None = None
    reason: str = Field(default="")


@dataclass(frozen=True)
class ConsolidationOutcome:
    """What consolidation did. ``item`` is the stored/updated memory (None for a NOOP)."""

    op: Op
    item: MemoryItem | None
    superseded_id: str | None = None


_JUDGE_PROMPT = (
    "You maintain a user's long-term memory. Decide how a NEW candidate fact relates to the most "
    "similar EXISTING memories, and return JSON matching the schema.\n"
    '- "noop": the candidate is already captured by an existing memory (a duplicate or '
    "restatement). Nothing new to store.\n"
    '- "update": the candidate CONTRADICTS or corrects exactly one existing memory about the same '
    "subject (e.g. a changed name, job, status). Set target_id to that memory's id and text to the "
    "corrected, self-contained statement.\n"
    '- "add": the candidate is new, independent information. \n'
    "Only choose update for a genuine contradiction about the same subject — not for a related but "
    "distinct fact. Never invent a target_id; use only the ids listed.\n\n"
)


def _judge_messages(text: str, related: Sequence[MemoryItem]) -> list[ChatMessage]:
    existing = "\n".join(f"- id={m.id}: {m.text}" for m in related)
    body = f"NEW candidate fact:\n{text}\n\nEXISTING related memories:\n{existing}\n"
    return [ChatMessage(Role.USER, _JUDGE_PROMPT + body)]


async def consolidate_fact(
    *,
    text: str,
    kind: MemoryKind,
    confidence: float,
    source: Mapping[str, str],
    store: MemoryStore,
    embed_provider: ModelProvider,
    embed_model: str,
    judge_provider: ModelProvider,
    judge_model: str,
    dedup_threshold: float = DEDUP_THRESHOLD,
    relate_threshold: float = RELATE_THRESHOLD,
    top_k: int = 5,
) -> ConsolidationOutcome:
    """Store ``text`` as a memory, reconciling it with existing ones. Raises ValueError if the text
    cannot be embedded (the caller decides whether that is fatal or skippable)."""
    text = text.strip()
    if not text:
        return ConsolidationOutcome(op="noop", item=None)

    embedding = await _embed(embed_provider, embed_model, text)
    related = [
        m
        for m in await store.search(embedding, top_k=top_k)
        if (m.score or 0.0) >= relate_threshold
    ]
    if not related:
        return ConsolidationOutcome(
            op="add", item=await _add(store, kind, text, embedding, confidence, source)
        )

    decision = await generate_structured(
        provider=judge_provider,
        model=judge_model,
        messages=_judge_messages(text, related),
        schema=_Decision,
    )
    related_ids = {m.id for m in related}

    # Fail closed to dedup-only: drop a near-duplicate, else add (no regression vs the old path).
    if decision is None:
        if related[0].score is not None and related[0].score >= dedup_threshold:
            return ConsolidationOutcome(op="noop", item=None)
        return ConsolidationOutcome(
            op="add", item=await _add(store, kind, text, embedding, confidence, source)
        )

    if decision.op == "noop":
        return ConsolidationOutcome(op="noop", item=None)

    if decision.op == "update" and decision.target_id in related_ids:
        new_text = (decision.text or text).strip() or text
        await store.supersede(decision.target_id)
        # Re-embed when the merged text differs so the stored vector matches what we keep.
        vector = (
            embedding if new_text == text else await _embed(embed_provider, embed_model, new_text)
        )
        item = await _add(store, kind, new_text, vector, confidence, source)
        return ConsolidationOutcome(op="update", item=item, superseded_id=decision.target_id)

    # "add", or an "update" naming an unknown id -> treat as a new fact.
    return ConsolidationOutcome(
        op="add", item=await _add(store, kind, text, embedding, confidence, source)
    )


async def _embed(provider: ModelProvider, model: str, text: str) -> Sequence[float]:
    result = await provider.embed([text], model)
    if not result.vectors or not result.vectors[0]:
        raise ValueError("embedding provider returned no vector")
    return result.vectors[0]


async def _add(
    store: MemoryStore,
    kind: MemoryKind,
    text: str,
    embedding: Sequence[float],
    confidence: float,
    source: Mapping[str, str],
) -> MemoryItem:
    return await store.add(
        id=str(uuid.uuid4()),
        kind=kind,
        text=text,
        embedding=embedding,
        confidence=confidence,
        source=source,
    )
