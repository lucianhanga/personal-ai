"""Multi-source graph path (#420): planner SourcePlan -> gather -> merge -> researcher.

Pins the additive state-graph delta: with sources wired the planner emits a SourcePlan, the gather
and merge nodes run, the researcher grounds on the merged evidence, and a unified `citations` event
carries source_kind. With NO sources the topology and event stream are exactly today's (safe
superset, regression-gated against the existing single-source pipeline test).
"""

from __future__ import annotations

import asyncio

from personalai_contracts.ports import (
    SOURCE_KIND_MEMORY,
    SOURCE_KIND_VECTOR,
    AgentContext,
    ChatMessage,
    Citation,
    Evidence,
    Role,
)
from personalai_contracts.testing import FakeModelProvider
from personalai_core import AgentEvent, InProcessExecutor, Registry, ToolGateway, run_graph
from personalai_core.gateway import RegisteredTool
from personalai_core.security.audit import AuditLog
from personalai_core.sources import GraphSource


def _gateway() -> ToolGateway:
    reg: Registry[RegisteredTool] = Registry("tool")
    return ToolGateway(reg, InProcessExecutor(), audit=AuditLog(), egress_check=lambda h: None)


def _drain(**kwargs: object) -> list[AgentEvent]:
    async def _run() -> list[AgentEvent]:
        return [ev async for ev in run_graph(**kwargs)]  # type: ignore[arg-type]

    return asyncio.run(_run())


class _StaticSource:
    def __init__(self, name: str, kind: str, items: list[Evidence]) -> None:
        self.name = name
        self.kind = kind
        self._items = items

    async def select(self, query: str, ctx: AgentContext | None) -> float | None:
        return None

    async def retrieve(self, query: str, budget: int, ctx: AgentContext | None) -> list[Evidence]:
        return self._items


def _vector_source() -> _StaticSource:
    return _StaticSource(
        "vector",
        SOURCE_KIND_VECTOR,
        [
            Evidence(
                "doc fact", 0.9, Citation("doc-1", "chunk 0"), SOURCE_KIND_VECTOR, {"name": "doc-1"}
            ),
        ],
    )


def _memory_source() -> _StaticSource:
    return _StaticSource(
        "memory",
        SOURCE_KIND_MEMORY,
        [
            Evidence(
                "user fact", 0.5, Citation("memory:1"), SOURCE_KIND_MEMORY, {"name": "Memory"}
            ),
        ],
    )


def test_no_sources_is_exactly_todays_pipeline() -> None:
    # Safe-superset regression gate: with no sources the event sequence is the existing
    # plan -> draft -> critique -> answer -> final (no gather/merge/citations events).
    events = _drain(
        messages=[ChatMessage(Role.USER, "hi")],
        provider=FakeModelProvider(),
        model="m",
        gateway=_gateway(),
        tools=[],
    )
    assert [e.type for e in events] == ["plan", "draft", "critique", "answer", "final"]


def test_multisource_emits_citations_with_source_kind() -> None:
    events = _drain(
        messages=[ChatMessage(Role.USER, "what do you know")],
        provider=FakeModelProvider(),
        model="m",
        gateway=_gateway(),
        tools=[],
        sources=[_vector_source(), _memory_source(), GraphSource()],
        query="what do you know",
    )
    types = [e.type for e in events]
    # The merge node emits a unified `citations` event before the researcher's draft.
    assert "citations" in types
    assert types.index("citations") < types.index("draft")
    cite_ev = next(e for e in events if e.type == "citations")
    assert cite_ev.output is not None
    cites = cite_ev.output["citations"]
    kinds = {c["source_kind"] for c in cites}
    assert kinds == {SOURCE_KIND_VECTOR, SOURCE_KIND_MEMORY}  # both cheap sources fused
    # The SourcePlan rode along (vector+memory floored on; graph stub pruned/empty).
    plan = cite_ev.output["source_plan"]
    assert "vector" in plan["sources"] and "memory" in plan["sources"]


def test_multisource_derives_query_from_last_user_message() -> None:
    # No explicit query -> planner/gather derive it from the last user message (_last_user_text).
    events = _drain(
        messages=[ChatMessage(Role.USER, "tell me about tea")],
        provider=FakeModelProvider(),
        model="m",
        gateway=_gateway(),
        tools=[],
        sources=[_vector_source()],
        # query omitted on purpose
    )
    assert "citations" in [e.type for e in events]


def test_multisource_with_only_empty_sources_grounds_on_nothing() -> None:
    # Sources that return nothing -> the merge produces an empty grounded block; the pipeline still
    # runs end to end and emits an (empty) citations event without error.
    empty = _StaticSource("vector", SOURCE_KIND_VECTOR, [])
    events = _drain(
        messages=[ChatMessage(Role.USER, "q")],
        provider=FakeModelProvider(),
        model="m",
        gateway=_gateway(),
        tools=[],
        sources=[empty, GraphSource()],
        query="q",
    )
    types = [e.type for e in events]
    assert types[-1] == "final"
    cite_ev = next(e for e in events if e.type == "citations")
    assert cite_ev.output is not None
    assert cite_ev.output["citations"] == []  # nothing retrieved


def test_multisource_grounds_researcher_and_still_finalizes() -> None:
    # The full pipeline still produces a single final answer (the researcher grounded on the merged
    # evidence). FakeModelProvider echoes the last message, so a draft+answer+final are present.
    events = _drain(
        messages=[ChatMessage(Role.USER, "q")],
        provider=FakeModelProvider(),
        model="m",
        gateway=_gateway(),
        tools=[],
        sources=[_vector_source(), _memory_source()],
        query="q",
    )
    types = [e.type for e in events]
    assert types[0] == "plan"
    assert types[-1] == "final"
    assert "citations" in types and "draft" in types
