"""Query-planner source-routing decision (#420 multi-source retrieval).

The planner node (``core/graph.py``) widens its free-text plan to ALSO emit this structured routing
decision via ``generate_structured`` (the same pattern as the verifier's :class:`Verdict`), so the
gather node can fan out across exactly the selected sources deterministically instead of parsing
free text. Cheap always-on sources (vector + memory) are floored on by the heuristic regardless of
what the model returns; this schema only ever GATES the expensive/optional sources (tools, and later
the deferred graph/KAG source). Not a versioned wire contract — internal to the planner.
"""

from __future__ import annotations

from personalai_contracts.schemas.base import StrictModel


class SourcePlan(StrictModel):
    """Which retrieval sources to consult for a question, and whether to fan them out in parallel.

    ``sources`` is a subset of the registered source NAMES. The planner may only ADD expensive
    sources to the always-on cheap floor (vector + memory) — it can never remove the grounded cheap
    sources, so a mis-route degrades to an extra retry, never a wrong (ungrounded) answer.
    """

    sources: list[str]
    rationale: str = ""
    parallel: bool = True
