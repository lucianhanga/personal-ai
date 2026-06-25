"""Multi-source gather + plan (#420): bounded-parallel fan-out and heuristic-first routing.

Pins: gather runs sources concurrently and is bounded/isolated (a failing source doesn't fail the
turn); plan floors vector+memory on, gates optionals via a structured call, and prunes by select().
"""

from __future__ import annotations

import asyncio
import time

from personalai_contracts.ports import (
    SOURCE_KIND_MEMORY,
    SOURCE_KIND_VECTOR,
    AgentContext,
    Citation,
    Evidence,
)
from personalai_contracts.testing import FakeModelProvider
from personalai_core.sources import GraphSource, gather_sources, plan_sources
from personalai_core.sources.gather import allocate_budgets


class _SlowSource:
    """A source that sleeps before returning, to prove gather runs them concurrently."""

    def __init__(self, name: str, kind: str, delay: float, n: int = 1) -> None:
        self.name = name
        self.kind = kind
        self._delay = delay
        self._n = n

    async def select(self, query: str, ctx: AgentContext | None) -> float | None:
        return None

    async def retrieve(self, query: str, budget: int, ctx: AgentContext | None) -> list[Evidence]:
        await asyncio.sleep(self._delay)
        return [
            Evidence(
                text=f"{self.name}-{i}",
                score=1.0 - i * 0.1,
                citation=Citation(source_id=f"{self.name}-{i}"),
                source_kind=self.kind,
            )
            for i in range(self._n)
        ]


class _BrokenSource:
    name = "broken"
    kind = "tool:broken"

    async def select(self, query: str, ctx: AgentContext | None) -> float | None:
        return None

    async def retrieve(self, query: str, budget: int, ctx: AgentContext | None) -> list[Evidence]:
        raise RuntimeError("source exploded")


def test_gather_runs_sources_in_parallel() -> None:
    # Two 50ms sources run concurrently -> total ~50ms, not ~100ms (proves asyncio.gather fan-out).
    a = _SlowSource("vector", SOURCE_KIND_VECTOR, 0.05)
    b = _SlowSource("memory", SOURCE_KIND_MEMORY, 0.05)

    async def _run() -> dict[str, list[Evidence]]:
        return await gather_sources(sources=[a, b], query="q", token_budget=6000)

    started = time.perf_counter()
    result = asyncio.run(_run())
    elapsed = time.perf_counter() - started
    assert set(result) == {"vector", "memory"}
    assert elapsed < 0.09  # concurrent, not serial (~0.10s would be serial)


def test_gather_isolates_a_failing_source() -> None:
    good = _SlowSource("vector", SOURCE_KIND_VECTOR, 0.0)
    bad = _BrokenSource()

    async def _run() -> dict[str, list[Evidence]]:
        return await gather_sources(sources=[good, bad], query="q", token_budget=6000)

    result = asyncio.run(_run())
    assert result["vector"]  # the good source contributed
    assert result["broken"] == []  # the failing source degraded to [] (turn not failed)


def test_allocate_budgets_splits_with_floor() -> None:
    assert allocate_budgets(2, 6000) == 3000  # equal share
    assert allocate_budgets(10, 5) == 1  # floor (never zero)
    assert allocate_budgets(3, 0) == 0  # unbudgeted -> no per-source cap


def test_plan_floors_vector_and_memory_without_a_router_call() -> None:
    # With only cheap always-on sources, plan_sources skips the structured call entirely and floors
    # both on — matching today's unconditional retrieve+recall (zero regression).
    vector = _SlowSource("vector", SOURCE_KIND_VECTOR, 0.0)
    memory = _SlowSource("memory", SOURCE_KIND_MEMORY, 0.0)

    async def _run() -> list[str]:
        chosen, plan = await plan_sources(
            query="q",
            sources=[vector, memory],
            provider=FakeModelProvider(),
            model="m",
        )
        return [s.name for s in chosen]

    assert asyncio.run(_run()) == ["vector", "memory"]


def test_plan_prunes_graph_stub_even_if_chosen() -> None:
    # The deferred graph stub returns select()=0.0, so even if the (fake) router names it, the
    # deterministic prune drops it -> NOTHING fires for graph. Vector stays floored on.
    vector = _SlowSource("vector", SOURCE_KIND_VECTOR, 0.0)
    graph = GraphSource()

    class _RouterPicksGraph(FakeModelProvider):
        async def generate(self, request):  # type: ignore[no-untyped-def]
            from personalai_contracts.ports import GenerationResult

            return GenerationResult(
                text='{"sources": ["graph"], "rationale": "x", "parallel": true}',
                model=request.model,
            )

    async def _run() -> list[str]:
        chosen, plan = await plan_sources(
            query="q",
            sources=[vector, graph],
            provider=_RouterPicksGraph(),
            model="m",
        )
        return [s.name for s in chosen]

    chosen = asyncio.run(_run())
    assert "graph" not in chosen  # pruned by select()=0.0
    assert "vector" in chosen  # cheap floor stays
