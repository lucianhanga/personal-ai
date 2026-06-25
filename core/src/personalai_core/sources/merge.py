"""Evidence-merge: cross-source dedup + RRF + the first cross-source token budget (#420).

The merge node takes ``{source_name: [Evidence, ...]}`` from the gather step and produces ONE
ranked, deduped, budget-fitted ``list[Evidence]`` plus the unified citation rows. Two invariants:

* **Cross-source fusion happens ONLY here.** Source-local scores (cosine vs memory similarity vs
  tool order) are not comparable, so ranking is **Reciprocal Rank Fusion across sources**
  (``1/(k+rank)``, k=60 canonical) — rank-based, no score normalization. Intra-vector RRF
  (dense+FTS) stays INSIDE the vector source; this node never re-fuses it (no double fusion).
* **The cross-source token budget lands here** — the first real budget in the system (today context
  is gated only by count caps; nothing fits to ``ollama_num_ctx``). A per-turn evidence budget is
  divided across the contributing sources with a **per-source floor** so no source is starved, then
  filled by interleaved RRF rank until the budget is hit.

Pure + deterministic (depends only on contracts types), so it is fully unit-testable with fakes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from personalai_contracts.ports import Citation, Evidence

# Canonical RRF constant (matches the intra-vector dense+FTS fusion and the doktokNG pattern).
RRF_K = 60

# A coarse token estimate (chars/4) — the same cheap heuristic the tier routing uses (#420). Good
# enough to keep the assembled evidence under the window; an exact tokenizer is not worth the dep.
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """A cheap chars/4 token estimate for budgeting (no tokenizer dependency)."""
    return (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN


def _dedup_key(ev: Evidence) -> tuple[str, str]:
    """The cross-source identity of an evidence item for dedup: its citation (source_id, locator)
    when present, else its normalized text. Two items with the same key are the SAME fact reached
    via different sources (e.g. a doc chunk also surfaced from memory)."""
    cid = ev.citation
    if cid.source_id:
        return (cid.source_id, cid.locator or "")
    return ("", " ".join(ev.text.split()).casefold())


# Provenance preference on a dedup tie: a vector chunk is higher-provenance than a tool snippet than
# memory than a graph stub. The winner KEEPS its identity; the loser's kind is recorded in
# ``merged_from`` so one [n] can honestly attribute the fact to both.
_PROVENANCE_RANK: dict[str, int] = {"vector": 3, "graph": 2, "memory": 1}


def _provenance_rank(source_kind: str) -> int:
    if source_kind.startswith("tool:"):
        return 2  # tool snippets rank with graph, below vector chunks
    return _PROVENANCE_RANK.get(source_kind, 0)


@dataclass(frozen=True)
class MergeResult:
    """The merge node output: the ordered, budget-fitted evidence and its unified citation rows."""

    evidence: list[Evidence]
    citations: list[dict[str, object]]


def _rrf_scores(per_source: Mapping[str, Sequence[Evidence]]) -> dict[int, float]:
    """RRF score per evidence item (keyed by identity) summed across the source rank lists.

    Each source contributes ``1/(k + rank)`` for an item at 0-based ``rank`` in its own list. An
    item present in several sources (same identity) accumulates each list's contribution — exactly
    the cross-source boost RRF is meant to give without comparing raw scores.
    """
    scores: dict[int, float] = {}
    for evidence in per_source.values():
        for rank, ev in enumerate(evidence):
            scores[id(ev)] = scores.get(id(ev), 0.0) + 1.0 / (RRF_K + rank)
    return scores


def merge_evidence(
    per_source: Mapping[str, Sequence[Evidence]],
    *,
    token_budget: int,
    per_source_floor: int = 1,
) -> MergeResult:
    """Fuse per-source evidence into one ranked, deduped, budget-fitted list + citation rows (#420).

    1. **Dedup** across sources by :func:`_dedup_key`; on a tie the higher-provenance source wins
       and the loser's ``source_kind`` is recorded in the winner's ``merged_from``.
    2. **Cross-source RRF** (k=60) ranks the survivors — rank-based, no score normalization.
    3. **Token budget**: fill by RRF rank until ``token_budget`` is hit, but guarantee each
       contributing source at least ``per_source_floor`` items first (so no source is crowded out).
       ``token_budget <= 0`` disables trimming (keep all, e.g. tests / unbudgeted callers).

    Returns evidence in final ``[n]`` order with ``score`` rewritten to the RRF score and citation
    rows carrying ``source_kind``/``merged_from`` (the additive provenance the UI surfaces).
    """
    rrf = _rrf_scores(per_source)

    # 1. Dedup by identity, keeping the highest-provenance representative and folding the others'
    # kinds into merged_from. We also accumulate the RRF score across the merged duplicates.
    winners: dict[tuple[str, str], Evidence] = {}
    merged_kinds: dict[tuple[str, str], set[str]] = {}
    merged_rrf: dict[tuple[str, str], float] = {}
    for evidence in per_source.values():
        for ev in evidence:
            key = _dedup_key(ev)
            merged_rrf[key] = merged_rrf.get(key, 0.0) + rrf.get(id(ev), 0.0)
            current = winners.get(key)
            if current is None:
                winners[key] = ev
                merged_kinds[key] = set()
            else:
                # Record BOTH kinds in merged_from; keep the higher-provenance representative.
                if _provenance_rank(ev.source_kind) > _provenance_rank(current.source_kind):
                    merged_kinds[key].add(current.source_kind)
                    winners[key] = ev
                else:
                    merged_kinds[key].add(ev.source_kind)

    # 2. Order by accumulated cross-source RRF (descending); ties keep first-seen (stable).
    ordered_keys = sorted(winners, key=lambda k: merged_rrf[k], reverse=True)

    # 3. Budget fill: floor each contributing source first, then fill by RRF rank until the budget
    # is spent. A source contributes its highest-RRF survivors up to the floor regardless of budget.
    selected: list[tuple[str, str]] = []
    spent = 0
    floored: dict[str, int] = {}

    def _tokens(key: tuple[str, str]) -> int:
        return estimate_tokens(winners[key].text)

    if token_budget > 0 and per_source_floor > 0:
        # Floor pass: walk the RRF order; admit an item if its source is still under the floor.
        for key in ordered_keys:
            kind = winners[key].source_kind
            if floored.get(kind, 0) < per_source_floor:
                selected.append(key)
                spent += _tokens(key)
                floored[kind] = floored.get(kind, 0) + 1

    # Fill pass: admit the remaining items by RRF order while they fit (or always, when unbudgeted).
    selected_set = set(selected)
    for key in ordered_keys:
        if key in selected_set:
            continue
        if token_budget <= 0:
            selected.append(key)
            continue
        cost = _tokens(key)
        if spent + cost <= token_budget:
            selected.append(key)
            selected_set.add(key)
            spent += cost

    # Re-order the selected set back into RRF order (the floor pass may have admitted out of order).
    final_keys = [k for k in ordered_keys if k in set(selected)]

    evidence_out: list[Evidence] = []
    citations: list[dict[str, object]] = []
    for n, key in enumerate(final_keys, start=1):
        ev = winners[key]
        extra = tuple(sorted(merged_kinds[key]))
        ranked = replace(ev, score=merged_rrf[key], merged_from=extra)
        evidence_out.append(ranked)
        citations.append(_citation_row(n, ranked))
    return MergeResult(evidence=evidence_out, citations=citations)


def serialize_evidence(ev: Evidence) -> dict[str, object]:
    """Render an :class:`Evidence` as a plain dict so it round-trips through the LangGraph
    (ormsgpack) checkpointer between the gather and merge nodes (#420) — Evidence/Citation
    dataclasses are not natively serializable by the checkpointer."""
    return {
        "text": ev.text,
        "score": ev.score,
        "source_id": ev.citation.source_id,
        "locator": ev.citation.locator,
        "source_kind": ev.source_kind,
        "metadata": dict(ev.metadata),
        "merged_from": list(ev.merged_from),
    }


def deserialize_evidence(raw: Mapping[str, Any]) -> Evidence:
    """Inverse of :func:`serialize_evidence`: rebuild an :class:`Evidence` from the transit dict."""
    locator = raw.get("locator")
    return Evidence(
        text=str(raw.get("text", "")),
        score=float(raw.get("score", 0.0)),
        citation=Citation(
            source_id=str(raw.get("source_id", "")),
            locator=str(locator) if locator is not None else None,
        ),
        source_kind=str(raw.get("source_kind", "")),
        metadata=dict(raw.get("metadata", {})),
        merged_from=tuple(raw.get("merged_from", ()) or ()),
    )


def _citation_row(n: int, ev: Evidence) -> dict[str, object]:
    """The unified citation dict (#420): the existing ``{n, source_id, locator, score, name}`` shape
    PLUS ``source_kind`` and ``merged_from`` — additive, so the UI's existing chips keep working and
    gain a per-source badge. ``name`` is read from metadata (the vector path stores it there)."""
    cid: Citation = ev.citation
    return {
        "n": n,
        "source_id": cid.source_id,
        "locator": cid.locator,
        "score": round(ev.score, 6),
        "name": ev.metadata.get("name"),
        "source_kind": ev.source_kind,
        "merged_from": list(ev.merged_from),
    }
