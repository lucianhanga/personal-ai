"""Conservative post-NER entity resolution (#465).

Local NER fragments a real-world entity into aliases ("M-net", "M-net Telekommunikations GmbH").
This pass folds same-type aliases into one canonical entity. It is deliberately CONSERVATIVE -- it
merges only:
  * within the SAME entity type (so the *product* "M-net Internet" is never folded into the *org*
    "M-net"), and
  * when one normalized name (legal-suffix stripped) EQUALS or is a token-PREFIX of another (so
    "M-net" -> "M-net Telekommunikations GmbH", but "Deutsche Bank" and "Bayerische Landesbank"
    stay separate, and a bare generic suffix like "Bank" is never force-merged).
Too-short/generic names (< 3 chars of content) are never merged. The actual DB merge (re-point
mentions/edges, sum counts, drop the alias) lives in PgEntityStore.merge_entity.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol

from personalai_storage_postgres import PgEntityStore

# Trailing company-form tokens dropped before comparing names (so "M-net GmbH" == "M-net").
_LEGAL_SUFFIXES = frozenset(
    {
        "gmbh",
        "mbh",
        "ag",
        "kgaa",
        "kg",
        "ohg",
        "ug",
        "eg",
        "se",
        "inc",
        "incorporated",
        "ltd",
        "limited",
        "llc",
        "llp",
        "plc",
        "co",
        "corp",
        "corporation",
        "company",
        "gesellschaft",
        "bv",
        "nv",
        "sa",
        "srl",
        "spa",
        "oy",
        "ab",
        "as",
        "sas",
    }
)


class _NamedEntity(Protocol):
    # Read-only so a frozen dataclass (the store's Entity) satisfies it structurally.
    @property
    def id(self) -> str: ...
    @property
    def type(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def mention_count(self) -> int: ...


def _norm_tokens(name: str) -> tuple[str, ...]:
    """Lowercase, drop punctuation (keep internal hyphens), split, strip trailing legal suffixes."""
    cleaned = re.sub(r"[^\w\s-]", " ", name.lower())
    tokens = [t for t in cleaned.split() if t]
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return tuple(tokens)


def _is_prefix(short: tuple[str, ...], long: tuple[str, ...]) -> bool:
    return len(short) < len(long) and long[: len(short)] == short


def plan_entity_merges(entities: Sequence[_NamedEntity]) -> list[tuple[str, list[str]]]:
    """Group same-type alias entities into ``(canonical_id, [alias_ids])``. Canonical = the longest,
    most-mentioned name in a cluster; aliases are equal or token-prefix names of the same type."""
    by_type: dict[str, list[_NamedEntity]] = defaultdict(list)
    for ent in entities:
        by_type[ent.type].append(ent)

    merges: list[tuple[str, list[str]]] = []
    for ents in by_type.values():
        toks = {e.id: _norm_tokens(e.name) for e in ents}
        # Canonicals first: longest token tuple, then most mentions -> aliases attach to them.
        order = sorted(ents, key=lambda e: (len(toks[e.id]), e.mention_count), reverse=True)
        canon_for: dict[str, str] = {}
        canonicals: list[_NamedEntity] = []
        for ent in order:
            tok = toks[ent.id]
            if not tok or len("".join(tok)) < 3:
                continue  # too short / generic to safely merge
            match = next(
                (c for c in canonicals if tok == toks[c.id] or _is_prefix(tok, toks[c.id])), None
            )
            if match is None:
                canonicals.append(ent)
                canon_for[ent.id] = ent.id
            else:
                canon_for[ent.id] = match.id
        groups: dict[str, list[str]] = defaultdict(list)
        for ent in ents:
            canon = canon_for.get(ent.id)
            if canon and canon != ent.id:
                groups[canon].append(ent.id)
        merges.extend((canon, aliases) for canon, aliases in groups.items())
    return merges


async def reconcile_entities(store: PgEntityStore, *, cap: int = 200) -> int:
    """Plan + apply conservative same-type alias merges over the corpus. Returns the number of alias
    entities folded into a canonical."""
    entities = await store.list_entities(limit=cap)
    merged = 0
    for canonical_id, alias_ids in plan_entity_merges(entities):
        for alias_id in alias_ids:
            await store.merge_entity(canonical_id=canonical_id, alias_id=alias_id)
            merged += 1
    return merged
