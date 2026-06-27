"""Co-occurrence ranking for the KAG ego-graph endpoint (#465). Pure logic -> no DB needed."""

from __future__ import annotations

from dataclasses import dataclass

from personalai_backend.app import _rank_cooccurring


@dataclass
class _E:
    id: str
    name: str


def test_ranks_by_shared_documents_excluding_focus_and_caps() -> None:
    focus = _E("f", "Focus")
    a, b, c = _E("a", "Alice"), _E("b", "Bob"), _E("c", "Carol")
    # focus shares: 3 docs with a, 2 with b, 1 with c. Each doc also lists focus (excluded).
    per_doc = [
        [focus, a, b, c],
        [focus, a, b],
        [focus, a],
    ]
    ranked = _rank_cooccurring(per_doc, "f", cap=10)
    assert [(e.id, w) for e, w in ranked] == [("a", 3), ("b", 2), ("c", 1)]
    # cap limits the result to the top-weighted neighbours.
    assert [e.id for e, _ in _rank_cooccurring(per_doc, "f", cap=2)] == ["a", "b"]


def test_empty_and_focus_only() -> None:
    assert _rank_cooccurring([], "f", cap=10) == []
    assert _rank_cooccurring([[_E("f", "Focus")]], "f", cap=10) == []  # only focus -> no neighbours


def test_ties_break_by_name() -> None:
    x, y = _E("x", "Zeta"), _E("y", "Alpha")
    ranked = _rank_cooccurring([[x, y]], "f", cap=10)
    assert [e.id for e, _ in ranked] == ["y", "x"]  # equal weight (1) -> alphabetical by name
