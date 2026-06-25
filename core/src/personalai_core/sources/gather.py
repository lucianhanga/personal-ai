"""Bounded-parallel gather across the planned :class:`RetrievalSource`s (#420).

Fans out ``source.retrieve(query, budget, ctx)`` across the planned sources with ``asyncio.gather``
INSIDE one step (not LangGraph ``Send``/superstep map) so all sources stay under one node's
timeout/runaway guard and the topology stays readable. The per-source token budget is allocated up
front (equal share with a floor) so each source is bounded before the merge node does the
authoritative cross-source trim. A single source failing is isolated: it contributes ``[]`` rather
than failing the whole turn (best-effort, mirroring the existing retrieval paths).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from personalai_contracts.ports import AgentContext, Evidence, RetrievalSource


def allocate_budgets(num_sources: int, token_budget: int, *, floor: int = 1) -> int:
    """The per-source token budget for the gather fan-out: an equal share of ``token_budget`` with a
    ``floor`` (so a source is never handed a zero/near-zero budget). ``token_budget <= 0`` means "no
    per-source cap" (the merge node does the trimming) -> returns 0."""
    if token_budget <= 0 or num_sources <= 0:
        return 0
    return max(floor, token_budget // num_sources)


async def gather_sources(
    *,
    sources: Sequence[RetrievalSource],
    query: str,
    token_budget: int,
    ctx: AgentContext | None = None,
) -> dict[str, list[Evidence]]:
    """Run the planned sources concurrently (bounded), returning ``{source_name: [Evidence, ...]}``.

    Each source gets an equal share of ``token_budget`` (with a floor). Exceptions in one source are
    swallowed to ``[]`` so a slow/broken source never fails the turn — the merge node simply has one
    fewer contributor. Order of the returned dict follows ``sources`` (registration order)."""
    if not sources:
        return {}
    per_source_budget = allocate_budgets(len(sources), token_budget)

    async def _one(src: RetrievalSource) -> list[Evidence]:
        try:
            return list(await src.retrieve(query, per_source_budget, ctx))
        except Exception:  # noqa: BLE001 - best-effort; a failed source contributes nothing
            return []

    results = await asyncio.gather(*(_one(s) for s in sources))
    return {src.name: evidence for src, evidence in zip(sources, results, strict=True)}
