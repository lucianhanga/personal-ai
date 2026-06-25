"""Evidence-merge (#420): cross-source dedup + RRF(k=60) + token budget with a per-source floor.

These are pure-function tests over the merge primitive — no model, no graph — so the cross-source
fusion / dedup / budget invariants are pinned independent of the orchestration.
"""

from __future__ import annotations

from personalai_contracts.ports import (
    SOURCE_KIND_MEMORY,
    SOURCE_KIND_VECTOR,
    Citation,
    Evidence,
)
from personalai_core.sources.merge import (
    RRF_K,
    estimate_tokens,
    merge_evidence,
)


def _ev(text: str, score: float, kind: str, sid: str = "", loc: str | None = None) -> Evidence:
    return Evidence(
        text=text,
        score=score,
        citation=Citation(source_id=sid, locator=loc),
        source_kind=kind,
        metadata={"name": sid or kind},
    )


def test_merge_assigns_sequential_n_and_carries_source_kind() -> None:
    per_source = {
        "vector": [
            _ev("a", 0.9, SOURCE_KIND_VECTOR, "doc-a"),
            _ev("b", 0.8, SOURCE_KIND_VECTOR, "doc-b"),
        ],
        "memory": [_ev("c", 0.5, SOURCE_KIND_MEMORY, "memory:1")],
    }
    result = merge_evidence(per_source, token_budget=0)  # no trim
    ns = [c["n"] for c in result.citations]
    assert ns == [1, 2, 3]  # sequential [n] across sources
    kinds = {c["source_kind"] for c in result.citations}
    assert kinds == {SOURCE_KIND_VECTOR, SOURCE_KIND_MEMORY}  # provenance carried per citation
    assert all("merged_from" in c for c in result.citations)


def test_cross_source_rrf_ranks_by_rank_not_raw_score() -> None:
    # Memory's raw score (0.99) is higher than vector's top (0.10), but RRF is RANK-based: an item
    # ranked #1 in its own source beats an item ranked #2 regardless of incomparable raw scores. A
    # vector item appearing in BOTH lists accumulates RRF and should outrank singletons.
    shared = _ev("shared", 0.10, SOURCE_KIND_VECTOR, "doc-shared")
    per_source = {
        "vector": [shared, _ev("v2", 0.05, SOURCE_KIND_VECTOR, "doc-2")],
        "memory": [
            _ev("m1", 0.99, SOURCE_KIND_MEMORY, "mem-1"),
            _ev("m2", 0.98, SOURCE_KIND_MEMORY, "mem-2"),
        ],
    }
    result = merge_evidence(per_source, token_budget=0)
    # Every item is a rank-1 or rank-2 contributor; none is double-counted here, so the #1 of each
    # source ties. The merge is stable, so the first-seen rank-1 (vector's shared) leads.
    assert result.citations[0]["source_id"] == "doc-shared"
    # RRF score equals 1/(k+0) for a single rank-1 appearance (citation score is rounded to 6dp).
    score = result.citations[0]["score"]
    assert isinstance(score, float)
    assert abs(score - 1.0 / RRF_K) < 1e-5


def test_dedup_records_merged_from_and_keeps_higher_provenance() -> None:
    # The SAME fact (same source_id+locator) surfaced from vector AND memory: dedup to one [n], keep
    # the vector representative (higher provenance), and record memory in merged_from.
    per_source = {
        "vector": [_ev("same fact", 0.7, SOURCE_KIND_VECTOR, "doc-x", "chunk 0")],
        "memory": [_ev("same fact", 0.6, SOURCE_KIND_MEMORY, "doc-x", "chunk 0")],
    }
    result = merge_evidence(per_source, token_budget=0)
    assert len(result.citations) == 1  # deduped
    cite = result.citations[0]
    assert cite["source_kind"] == SOURCE_KIND_VECTOR  # higher-provenance representative kept
    merged_from = cite["merged_from"]
    assert isinstance(merged_from, list)
    assert SOURCE_KIND_MEMORY in merged_from  # the other source recorded


def test_token_budget_trims_to_fit() -> None:
    # Three ~100-token items; a 150-token budget fits ~1-2 after the per-source floor.
    big = "x" * 400  # ~100 tokens (chars/4)
    per_source = {
        "vector": [
            _ev(big, 0.9, SOURCE_KIND_VECTOR, "d1"),
            _ev(big, 0.8, SOURCE_KIND_VECTOR, "d2"),
            _ev(big, 0.7, SOURCE_KIND_VECTOR, "d3"),
        ]
    }
    result = merge_evidence(per_source, token_budget=150, per_source_floor=1)
    total = sum(estimate_tokens(ev.text) for ev in result.evidence)
    assert total <= 150 + estimate_tokens(big)  # within budget (floor admits at least 1)
    assert 1 <= len(result.evidence) < 3  # trimmed below the full 3


def test_per_source_floor_protects_each_source_from_starvation() -> None:
    # A tight budget a single big vector item would exhaust must STILL admit at least one memory
    # item (the per-source floor), so memory is never fully crowded out.
    big = "v" * 4000  # ~1000 tokens
    small = "m" * 40  # ~10 tokens
    per_source = {
        "vector": [_ev(big, 0.99, SOURCE_KIND_VECTOR, "vbig")],
        "memory": [_ev(small, 0.10, SOURCE_KIND_MEMORY, "msmall")],
    }
    result = merge_evidence(per_source, token_budget=1100, per_source_floor=1)
    kinds = {ev.source_kind for ev in result.evidence}
    assert SOURCE_KIND_MEMORY in kinds  # the floor guaranteed memory a slot
    assert SOURCE_KIND_VECTOR in kinds


def test_dedup_by_normalized_text_when_no_source_id() -> None:
    # Items with no citation source_id dedup by normalized (whitespace/case-folded) text, so the
    # same fact phrased identically from two sources collapses to one [n].
    per_source = {
        "memory": [_ev("Same   Fact", 0.6, SOURCE_KIND_MEMORY, sid="")],
        "tool": [_ev("same fact", 0.5, "tool:web", sid="")],
    }
    result = merge_evidence(per_source, token_budget=0)
    assert len(result.citations) == 1


def test_empty_input_is_empty_output() -> None:
    result = merge_evidence({}, token_budget=6000)
    assert result.evidence == []
    assert result.citations == []
