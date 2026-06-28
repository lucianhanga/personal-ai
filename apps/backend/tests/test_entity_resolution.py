"""Conservative entity resolution (#465): same-type, prefix-only merge planner. Pure -- no DB."""

from __future__ import annotations

from dataclasses import dataclass

from personalai_backend.entity_resolution import _norm_tokens, plan_entity_merges


@dataclass
class _E:
    id: str
    type: str
    name: str
    mention_count: int


def test_norm_tokens_strips_legal_suffix_and_punct() -> None:
    assert _norm_tokens("M-net Telekommunikations GmbH") == ("m-net", "telekommunikations")
    assert _norm_tokens("M-net") == ("m-net",)
    assert _norm_tokens("Acme, Inc.") == ("acme",)


def test_merges_same_type_prefix_alias_only() -> None:
    ents = [
        _E("1", "org", "M-net Telekommunikations GmbH", 14),
        _E("2", "org", "M-net", 3),
        _E("3", "product", "M-net Internet", 4),  # different TYPE -> never merged
    ]
    # "M-net" (org) folds into the longer org canonical; the product stays separate.
    assert plan_entity_merges(ents) == [("1", ["2"])]


def test_does_not_overmerge_distinct_names() -> None:
    ents = [
        _E("1", "org", "Deutsche Bank", 5),
        _E("2", "org", "Bayerische Landesbank", 4),
        _E("3", "org", "Bank", 2),  # NOT a token-prefix of either -> not force-merged
    ]
    assert plan_entity_merges(ents) == []


def test_equal_names_dedup_to_most_mentioned() -> None:
    ents = [_E("1", "org", "Acme", 2), _E("2", "org", "ACME", 9)]
    assert plan_entity_merges(ents) == [("2", ["1"])]  # canonical = most-mentioned


def test_too_short_generic_not_merged() -> None:
    # "AB" / "AB Corp" both normalize to ("ab",) (<3 chars of content) -> never merged.
    ents = [_E("1", "org", "AB", 5), _E("2", "org", "AB Corp", 3)]
    assert plan_entity_merges(ents) == []
