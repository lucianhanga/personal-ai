"""LLM-based named-entity + relation extraction for KAG (#451).

A best-effort pass that asks the local model for a structured list of named entities (and simple
relations) found in a document's text. Structured output makes the result a typed object rather than
prose, and a fail-closed ``generate_structured`` returns nothing rather than guessing -- so a model
that refuses or drifts simply yields no entities, never a crash.

Local-model note: on the Qwen3 MoE (``...a3b``) the ``think=False`` + JSON-format combination emits
markdown prose instead of JSON, so for that arch we prepend a ``/no_think`` system line (which makes
thinking run silently and restores valid JSON). Entities cluster near a document's start, so we cap
the text to ``max_chars`` for the first pass; full per-chunk extraction is a future refinement.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from personalai_contracts.ports import ChatMessage, ModelProvider, Role
from personalai_core.structured import generate_structured

EntityType = Literal["person", "org", "location", "date", "product", "event", "other"]


class ExtractedEntity(BaseModel):
    """One named entity found in the text."""

    type: EntityType
    name: str


class ExtractedRelation(BaseModel):
    """A directed relationship between two entity NAMES (resolved to ids by the caller)."""

    src: str
    relation: str
    dst: str


class ExtractedEntities(BaseModel):
    """The structured NER result for one document."""

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)


_NER_PROMPT = (
    "You are a named-entity extractor. From the user's document text, extract the REAL named "
    "entities actually mentioned -- people, organizations, locations, dates, products, events -- "
    "and the simple relations between them. Do NOT invent entities that are not in the text. Use a "
    "type from this exact set: person, org, location, date, product, event, other. Each relation "
    "is a short predicate (e.g. 'works_at', 'located_in') between two entity names you also "
    "returned. Return ONLY the structured result."
)


def _is_moe(model: str) -> bool:
    # Qwen3 MoE (qwen35moe arch) needs the /no_think prefix for reliable JSON (see module doc).
    return "a3b" in model


async def extract_entities(
    text: str, *, provider: ModelProvider, model: str, max_chars: int = 6000
) -> ExtractedEntities:
    """Extract entities + relations from ``text`` (capped to ``max_chars``). Best-effort: returns an
    empty result if there is no text or the model fails to produce valid structured output."""
    capped = text.strip()[:max_chars]
    if not capped:
        return ExtractedEntities()
    messages: list[ChatMessage] = []
    if _is_moe(model):
        messages.append(ChatMessage(Role.SYSTEM, "/no_think"))
    messages.append(ChatMessage(Role.SYSTEM, _NER_PROMPT))
    messages.append(ChatMessage(Role.USER, capped))
    result = await generate_structured(
        provider=provider, model=model, messages=messages, schema=ExtractedEntities
    )
    return result if result is not None else ExtractedEntities()
