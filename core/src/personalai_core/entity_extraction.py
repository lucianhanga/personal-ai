"""LLM-based named-entity + relation extraction for KAG (#451).

A best-effort pass that asks the local model for a structured list of named entities (and simple
relations) found in a document's text. Structured output makes the result a typed object rather than
prose, and a fail-closed ``generate_structured`` returns nothing rather than guessing -- so a model
that refuses or drifts simply yields no entities, never a crash.

Aggressive collection (#465): the KAG is only as good as what NER captures, so we extract over the
*whole* document, not just its head. The text is split into overlapping windows and each window is
extracted independently, then the per-window results are merged and de-duplicated on the canonical
``(type, normalized-name)`` key. Smaller windows keep the model's attention high (recall drops on a
large blob), the overlap stops an entity straddling a boundary from being missed, and the prompt
asks for an *exhaustive* sweep rather than a conservative top-few. A vendor/sender that appears only
on page 3 of an invoice is now captured -- which is what makes corpus-wide enumeration ("how many
M-Net invoices") work. ``max_windows`` bounds the cost on very large documents.

Local-model note: on the Qwen3 MoE (``...a3b``) the ``think=False`` + JSON-format combination emits
markdown prose instead of JSON, so for that arch we prepend a ``/no_think`` system line (which makes
thinking run silently and restores valid JSON).
"""

from __future__ import annotations

import re
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
    "You are a named-entity extractor. Extract ONLY the meaningful named entities: people; "
    "organizations and companies (vendors, senders, issuers); locations; products; events; and the "
    "document's KEY dates (e.g. an issue or due date -- NOT every date that appears). Do NOT "
    "extract identifiers, account / IBAN / BIC / card / phone numbers, monetary amounts, URLs, "
    "e-mail addresses, or codes -- skip them entirely (do NOT use the 'other' type). Be selective: "
    "the entities that matter, not every fragment, and do not invent anything not in the text. Use "
    "a type from this EXACT set: person, org, location, date, product, event. Return ONLY entities."
)

# Whole-document coverage. Windows are deliberately SMALL: beyond recall (a model loses entities in
# a huge blob). Window size is MODEL-AWARE: the Qwen3 MoE returns EMPTY structured output on large
# windows -- a ~4000-char window came back with zero tokens -- so it needs a SMALL window; dense
# models (e.g. qwen3:14b) have no such limit and run far faster on a BIG window (fewer LLM calls per
# document). Overlap stops a boundary-straddling entity from being lost; max_windows caps the
# LLM-pass count on a very large document.
_MOE_WINDOW_CHARS = 1024  # the MoE breaks above ~this; keep it small
_DENSE_WINDOW_CHARS = 4096  # dense models handle big windows -> 3-4x fewer calls -> much faster
_OVERLAP_CHARS = 150
_MAX_WINDOWS = 30


def _is_moe(model: str) -> bool:
    # Qwen3 MoE (qwen35moe arch) needs the /no_think prefix for reliable JSON (see module doc).
    return "a3b" in model


_IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{8,30}$")
_BIC_RE = re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")


def _looks_like_entity_name(name: str) -> bool:
    """Reject strings that are clearly identifiers/codes, not names. Local models over-extract these
    (IBANs, BICs, tax/registration numbers, account codes, phones) and -- with no catch-all type --
    mislabel them as org/location/etc. This deterministic guard drops them regardless of the label.
    Dates are filtered out by the caller before this runs (they are legitimately numeric)."""
    s = name.strip()
    if not s:
        return False
    letters = sum(c.isalpha() for c in s)
    digits = sum(c.isdigit() for c in s)
    if letters == 0:
        return False  # pure number / punctuation (phone, code, "143/163/40289")
    if digits and digits / (letters + digits) >= 0.5:
        return False  # digit-dominated -> account / tax id / registration number
    compact = s.replace(" ", "")
    if _IBAN_RE.match(compact) or _BIC_RE.match(compact):
        return False  # e.g. DE72 7605 ... (IBAN), SSKNDE77 / BYLADEMM (BIC)
    # reject e-mails / URLs
    return "@" not in s and not s.lower().startswith(("http://", "https://", "www."))


def _default_window(model: str) -> int:
    """Small window for the MoE (it returns empty on large windows); big window for dense models."""
    return _MOE_WINDOW_CHARS if _is_moe(model) else _DENSE_WINDOW_CHARS


def _windows(text: str, window: int, overlap: int, max_windows: int) -> list[str]:
    """Split ``text`` into overlapping windows, bounded by ``max_windows`` (the tail of an
    over-long document is dropped rather than ballooning the LLM-pass count)."""
    if len(text) <= window:
        return [text]
    step = max(1, window - overlap)
    out: list[str] = []
    start = 0
    while start < len(text) and len(out) < max_windows:
        out.append(text[start : start + window])
        start += step
    return out


async def _extract_window(text: str, *, provider: ModelProvider, model: str) -> ExtractedEntities:
    messages: list[ChatMessage] = []
    if _is_moe(model):
        messages.append(ChatMessage(Role.SYSTEM, "/no_think"))
    messages.append(ChatMessage(Role.SYSTEM, _NER_PROMPT))
    messages.append(ChatMessage(Role.USER, text))
    result = await generate_structured(
        provider=provider, model=model, messages=messages, schema=ExtractedEntities
    )
    return result if result is not None else ExtractedEntities()


async def extract_entities(
    text: str,
    *,
    provider: ModelProvider,
    model: str,
    window: int | None = None,
    overlap: int = _OVERLAP_CHARS,
    max_windows: int = _MAX_WINDOWS,
) -> ExtractedEntities:
    """Extract entities + relations from the WHOLE of ``text`` via overlapping windows, merged and
    de-duplicated. ``window`` defaults to a MODEL-AWARE size (small for the MoE, large for dense
    models). Best-effort: returns an empty result if there is no text; a window that fails to
    produce valid structured output contributes nothing rather than aborting the document."""
    if window is None:
        window = _default_window(model)
    cleaned = text.strip()
    if not cleaned:
        return ExtractedEntities()

    merged_entities: dict[tuple[str, str], ExtractedEntity] = {}
    merged_relations: dict[tuple[str, str, str], ExtractedRelation] = {}
    for window_text in _windows(cleaned, window, overlap, max_windows):
        result = await _extract_window(window_text, provider=provider, model=model)
        for ent in result.entities:
            norm = " ".join(ent.name.strip().lower().split())
            if not norm:
                continue
            # Drop identifiers/codes the local model over-extracts and mislabels (e.g. an IBAN or
            # BIC tagged as a 'location'). Dates are exempt -- they are numeric by nature.
            if ent.type != "date" and not _looks_like_entity_name(ent.name):
                continue
            merged_entities.setdefault((ent.type, norm), ent)
        for rel in result.relations:
            key = (
                rel.src.strip().lower(),
                rel.relation.strip().lower(),
                rel.dst.strip().lower(),
            )
            if all(key):
                merged_relations.setdefault(key, rel)

    return ExtractedEntities(
        entities=list(merged_entities.values()),
        relations=list(merged_relations.values()),
    )
