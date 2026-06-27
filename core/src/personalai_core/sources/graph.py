"""GraphSource: KAG aggregation for enumeration / counting questions (#465).

Plain RAG retrieves passages -- it cannot answer "how many invoices from M-Net?" (it returns a few
matching chunks, not a count). This source answers count/enumeration questions over the knowledge
graph: it detects a counting intent (``select``), extracts the target entity from the question,
looks it up in the entity store via an INJECTED counter (so core stays free of the storage layer),
and returns one :class:`Evidence` stating the document count. Non-count queries get nothing
(``select`` returns ``0.0`` -> pruned by the planner), so ordinary retrieval is unaffected.

The counter is injected by the backend (which owns the tenant-scoped entity store); with no counter
wired this degrades to the previous no-op stub (returns nothing).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence

from pydantic import BaseModel

from personalai_contracts.ports import (
    SOURCE_KIND_GRAPH,
    AgentContext,
    ChatMessage,
    Citation,
    Evidence,
    ModelProvider,
    Role,
)
from personalai_core.structured import generate_structured

# Given a name, return matching entities as ``(name, type, document_count)`` strongest-match first.
EntityCounter = Callable[[str], Awaitable[Sequence[tuple[str, str, int]]]]

# Counting / enumeration intent. Deterministic so the planner can self-elect this source reliably.
_COUNT_RE = re.compile(
    r"\b(how many|how much|number of|count (of|the)|list (all|every|the)|enumerate|"
    r"which .*\b(documents?|invoices?|files?|records?))\b",
    re.IGNORECASE,
)


def _is_count_query(query: str) -> bool:
    return bool(_COUNT_RE.search(query or ""))


class _Target(BaseModel):
    """The single entity the user wants counted/listed, extracted from their question."""

    entity: str


class GraphSource:
    """KAG aggregation source: answers count/enumeration questions over the entity graph (#465)."""

    kind = SOURCE_KIND_GRAPH
    name = "graph"

    def __init__(
        self,
        *,
        counter: EntityCounter | None = None,
        provider: ModelProvider | None = None,
        model: str = "",
    ) -> None:
        self._counter = counter
        self._provider = provider
        self._model = model

    async def select(self, query: str, ctx: AgentContext | None) -> float | None:
        # Self-elect on a counting question (only when a counter is wired); never otherwise.
        return 0.9 if (self._counter is not None and _is_count_query(query)) else 0.0

    async def retrieve(
        self, query: str, budget: int, ctx: AgentContext | None
    ) -> Sequence[Evidence]:
        if self._counter is None or not _is_count_query(query):
            return []
        name = await self._extract_entity(query)
        if not name:
            return []
        matches = await self._counter(name)
        if not matches:
            return []
        ename, etype, count = matches[0]
        text = (
            f"Knowledge graph (exact count): the {etype} '{ename}' is recorded in {count} "
            f"document(s) in the corpus. Use this count to answer enumeration questions."
        )
        return [
            Evidence(
                text=text,
                score=1.0,
                citation=Citation(source_id=f"graph:{ename}", locator="count"),
                source_kind=SOURCE_KIND_GRAPH,
                metadata={"name": "Knowledge graph", "entity": ename, "count": count},
            )
        ]

    async def _extract_entity(self, query: str) -> str:
        """Pull the target entity name out of the question. Uses a bounded structured LLM call when
        a provider is wired; falls back to stripping the count phrasing."""
        if self._provider is None:
            return _COUNT_RE.sub("", query).strip(" ?.")
        result = await generate_structured(
            provider=self._provider,
            model=self._model,
            messages=[
                ChatMessage(
                    Role.SYSTEM,
                    "Extract the SINGLE entity (organization, person, place, product, or topic) "
                    "the user wants counted or listed from their question. Return only its name, "
                    "no extra words.",
                ),
                ChatMessage(Role.USER, query),
            ],
            schema=_Target,
        )
        return result.entity.strip() if result is not None else ""
