"""GraphSource: the deferred KAG / GraphRAG source as a no-op :class:`RetrievalSource` stub (#420).

Registered now so the merge / provenance / token-budget machinery already accounts for a graph
source and the seam shape is proven — but it does NO graph work and returns NOTHING. KAG / GraphRAG
is deferred to M11 / #409 (see the #420 "keep KAG as a deferred seam" decision). It lights up later
by replacing this stub's body with a real graph traversal; the merge node and the
citation/provenance contract need no change. ``select`` returns ``0.0`` (never applicable) and
``retrieve`` returns ``[]`` so NOTHING renders for it today.
"""

from __future__ import annotations

from collections.abc import Sequence

from personalai_contracts.ports import SOURCE_KIND_GRAPH, AgentContext, Evidence


class GraphSource:
    """A no-op KAG/GraphRAG source proving the seam; deferred to M11/#409 (returns nothing)."""

    kind = SOURCE_KIND_GRAPH
    name = "graph"

    async def select(self, query: str, ctx: AgentContext | None) -> float | None:
        return 0.0  # never applicable until the graph store exists.

    async def retrieve(
        self, query: str, budget: int, ctx: AgentContext | None
    ) -> Sequence[Evidence]:
        return []  # deferred: no graph wiring in this issue.
