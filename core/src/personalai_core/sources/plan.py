"""Query-planner source routing (#420): pick which :class:`RetrievalSource`s to consult.

Heuristic-first, LLM-structured fallback (keeps cost down + is testable):

* **Cheap, always-on sources are floored ON** (vector + memory, whenever their feature flags are on)
  — this matches today's unconditional ``_retrieve_context`` + ``_memory_context``, so standard mode
  has ZERO routing regression. The planner can only ADD expensive sources, never remove the grounded
  cheap floor (a mis-route degrades to a retry, never an ungrounded answer).
* The model decides ONLY the expensive/optional sources (tools today; the deferred graph later) via
  ONE bounded :func:`generate_structured` call against the :class:`SourcePlan` schema — the same
  pattern as the verifier's ``Verdict`` (no new dependency, ADR-0012). When there is nothing
  optional to gate, the structured call is skipped entirely (no cost).
* A source's optional ``select`` score then **prunes** the model's optional picks deterministically
  (drop a source the planner chose but whose ``select`` says it's not applicable, e.g. the deferred
  graph stub returning 0.0), so a mis-route can't fire an inapplicable source.
"""

from __future__ import annotations

from collections.abc import Sequence

from personalai_contracts.ports import (
    SOURCE_KIND_MEMORY,
    SOURCE_KIND_VECTOR,
    AgentContext,
    ChatMessage,
    ModelProvider,
    RetrievalSource,
    Role,
)
from personalai_contracts.schemas import SourcePlan
from personalai_core.structured import generate_structured

# The cheap, grounded source kinds that are floored ON whenever present (never gated by the model).
_ALWAYS_ON_KINDS = frozenset({SOURCE_KIND_VECTOR, SOURCE_KIND_MEMORY})

# A source's select() score must clear this to survive pruning (drops the deferred graph stub at
# 0.0).
_SELECT_PRUNE_THRESHOLD = 0.0

_ROUTER_PROMPT = (
    "You are a retrieval router. Given the user's request and a list of OPTIONAL retrieval "
    "sources, return JSON naming ONLY the optional sources that are actually needed to answer (an "
    "empty list if none are). Cheap grounded sources (documents, memory) are always consulted and "
    "are NOT in your list — do not add them. Prefer fewer sources; only add an expensive source "
    "(e.g. live web search) when the request genuinely needs data it provides."
)


def _always_on(sources: Sequence[RetrievalSource]) -> list[RetrievalSource]:
    return [s for s in sources if s.kind in _ALWAYS_ON_KINDS]


def _optional(sources: Sequence[RetrievalSource]) -> list[RetrievalSource]:
    return [s for s in sources if s.kind not in _ALWAYS_ON_KINDS]


async def plan_sources(
    *,
    query: str,
    sources: Sequence[RetrievalSource],
    provider: ModelProvider,
    model: str,
    ctx: AgentContext | None = None,
) -> tuple[list[RetrievalSource], SourcePlan]:
    """Select the sources to gather for ``query``: the always-on cheap floor + the model-gated,
    ``select``-pruned optional sources. Returns the chosen sources (in registration order) and the
    :class:`SourcePlan` (for the trace / tests). Fails closed to the always-on floor on any router
    error (``generate_structured`` returning ``None``)."""
    always = _always_on(sources)
    optional = _optional(sources)

    if not optional:
        # Nothing to gate -> skip the structured call entirely (no cost); floor is the whole plan.
        floor_plan = SourcePlan(
            sources=[s.name for s in always], rationale="cheap sources only", parallel=True
        )
        return always, floor_plan

    catalog = "\n".join(f"- {s.name} ({s.kind})" for s in optional)
    routed = await generate_structured(
        provider=provider,
        model=model,
        messages=[
            ChatMessage(Role.SYSTEM, _ROUTER_PROMPT),
            ChatMessage(
                Role.USER,
                f"Request:\n{query}\n\nOptional sources:\n{catalog}\n\n"
                "Return the optional source names to use.",
            ),
        ],
        schema=SourcePlan,
    )
    chosen_optional_names = set(routed.sources) if routed is not None else set()

    chosen_optional: list[RetrievalSource] = []
    for src in optional:
        if src.name not in chosen_optional_names:
            continue
        # Deterministic prune: drop a planner pick whose select() says it's not applicable (e.g. the
        # deferred graph stub's 0.0). select() returning None means "no opinion" -> keep it.
        score = await src.select(query, ctx)
        if score is not None and score <= _SELECT_PRUNE_THRESHOLD:
            continue
        chosen_optional.append(src)

    chosen = always + chosen_optional
    effective = SourcePlan(
        sources=[s.name for s in chosen],
        rationale=routed.rationale
        if routed is not None
        else "router unavailable; cheap floor only",
        parallel=routed.parallel if routed is not None else True,
    )
    return chosen, effective
