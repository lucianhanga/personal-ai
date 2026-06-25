"""MemorySource: long-term memory (``recall``) as a :class:`RetrievalSource` (#420).

Wraps the existing :func:`personalai_core.memory_extraction.recall` (the #431 query-cap stays inside
it) and maps each ``MemoryItem`` to provenance-tagged :class:`Evidence` with
``source_kind="memory"`` and a synthetic memory citation. Memory is cheap and always-on, so
``select`` returns ``None`` (the planner/heuristic floors it on, matching today's unconditional
``_memory_context``).
"""

from __future__ import annotations

from collections.abc import Sequence

from personalai_contracts.ports import (
    SOURCE_KIND_MEMORY,
    AgentContext,
    Citation,
    Evidence,
    MemoryStore,
    ModelProvider,
)
from personalai_core.memory_extraction import recall
from personalai_core.sources.merge import estimate_tokens


class MemorySource:
    """Adapt long-term memory recall to the multi-source :class:`RetrievalSource` seam."""

    kind = SOURCE_KIND_MEMORY
    name = "memory"

    def __init__(
        self,
        *,
        embed_provider: ModelProvider,
        embed_model: str,
        store: MemoryStore,
        top_k: int = 5,
    ) -> None:
        self._embed_provider = embed_provider
        self._embed_model = embed_model
        self._store = store
        self._top_k = top_k

    async def select(self, query: str, ctx: AgentContext | None) -> float | None:
        return None  # cheap + always-on; the planner/heuristic floors it.

    async def retrieve(
        self, query: str, budget: int, ctx: AgentContext | None
    ) -> Sequence[Evidence]:
        items = await recall(
            query=query,
            embed_provider=self._embed_provider,
            embed_model=self._embed_model,
            store=self._store,
            top_k=self._top_k,
        )
        evidence: list[Evidence] = []
        spent = 0
        for item in items:
            cost = estimate_tokens(item.text)
            if budget > 0 and spent + cost > budget and evidence:
                break
            evidence.append(
                Evidence(
                    text=item.text,
                    score=item.score if item.score is not None else 0.0,
                    citation=Citation(source_id=f"memory:{item.id}", locator=str(item.kind)),
                    source_kind=SOURCE_KIND_MEMORY,
                    metadata={"name": "Memory", "kind": str(item.kind)},
                )
            )
            spent += cost
        return evidence
