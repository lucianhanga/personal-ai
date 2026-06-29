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


def _content(events: list[AgentEvent]) -> list[AgentEvent]:
    """Drop the generic ``stage`` progress heartbeats (#465) -- UI chrome at every node entry, not
    part of the pinned content sequence."""
    return [e for e in events if e.type != "stage"]


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
    assert [e.type for e in _content(events)] == ["plan", "draft", "critique", "answer", "final"]


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


def test_multisource_emits_retrieval_progress_running_then_done() -> None:
    # Live retrieval progress (#462): the gather node brackets its fan-out with a `retrieval`
    # running frame (before) and a done frame (after, with per-source hit counts), so the otherwise
    # silent planner->researcher gap shows context being assembled. Both precede the merge node's
    # `citations` event and the researcher's draft.
    events = _drain(
        messages=[ChatMessage(Role.USER, "what do you know")],
        provider=FakeModelProvider(),
        model="m",
        gateway=_gateway(),
        tools=[],
        sources=[_vector_source(), _memory_source()],
        query="what do you know",
    )
    retrievals = [e for e in events if e.type == "retrieval"]
    assert [e.output["status"] for e in retrievals if e.output] == ["running", "done"]
    running, done = retrievals
    assert running.output is not None and done.output is not None
    # The running frame names the sources being queried; the done frame carries per-source counts.
    assert set(running.output["sources"]) == {"vector", "memory"}
    assert done.output["counts"] == {"vector": 1, "memory": 1}
    assert done.output["hits"] == 2
    # Progress brackets the fan-out, landing before the merge's citations and the researcher draft.
    types = [e.type for e in events]
    assert types.index("retrieval") < types.index("citations") < types.index("draft")


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
    types = [e.type for e in _content(events)]
    assert types[0] == "plan"
    assert types[-1] == "final"
    assert "citations" in types and "draft" in types


class _CapturingVerifier(FakeModelProvider):
    """Records the SYSTEM context the verifier judge sees, so a test can assert the tool-armed
    independent lookup was folded in. The judge always passes (no retry); other nodes echo."""

    def __init__(self) -> None:
        super().__init__(name="cap")
        self.verifier_system = ""

    async def generate(self, request):  # type: ignore[no-untyped-def]
        from personalai_contracts.ports import GenerationResult

        sys_text = " ".join(m.content for m in request.messages if m.role == Role.SYSTEM)
        last = request.messages[-1].content if request.messages else ""
        if "You are the verifier" in sys_text or "Draft answer to verify" in last:
            self.verifier_system = sys_text
            return GenerationResult(text='{"verdict": "pass", "reason": "r"}', model=request.model)
        if "Draft answer to review" in last:
            return GenerationResult(text="OK: fine", model=request.model)  # critic: no reflection
        return GenerationResult(text="answer", model=request.model)


class _CapturingCritic(FakeModelProvider):
    """Records the SYSTEM context the critic sees (so a test can assert merged multi-source evidence
    survived to the judge even when the researcher called no tools). Critic returns OK."""

    def __init__(self) -> None:
        super().__init__(name="cap-critic")
        self.critic_system = ""

    async def generate(self, request):  # type: ignore[no-untyped-def]
        from personalai_contracts.ports import GenerationResult

        sys_text = " ".join(m.content for m in request.messages if m.role == Role.SYSTEM)
        last = request.messages[-1].content if request.messages else ""
        if "Draft answer to review" in last:
            self.critic_system = sys_text
            return GenerationResult(text="OK: looks sound", model=request.model)
        return GenerationResult(text="answer", model=request.model)


def test_merged_evidence_reaches_the_critic_when_researcher_calls_no_tools() -> None:
    # Regression (#420): the merge node's fused evidence lives in `merged_evidence`, a key the
    # researcher never overwrites — so the critic judges against it even when the researcher answers
    # from the grounded block WITHOUT calling tools (the FakeModelProvider never calls tools, so the
    # researcher's own `evidence` is empty). Before the fix the researcher clobbered `evidence` to
    # [] and the critic judged blind.
    provider = _CapturingCritic()
    _drain(
        messages=[ChatMessage(Role.USER, "what do you know")],
        provider=provider,
        model="m",
        gateway=_gateway(),
        tools=[],
        sources=[_vector_source()],
        query="what do you know",
    )
    assert "doc fact" in provider.critic_system  # the merged vector evidence reached the judge


def test_critic_runs_independent_lookup_when_it_is_the_last_judge() -> None:
    # Tool-armed critic (#465): in STANDARD mode there is no verifier, so the critic is the last
    # judge and runs the bounded independent fact-check when armed (verifier_tools on + sources).
    provider = _CapturingCritic()
    _drain(
        messages=[ChatMessage(Role.USER, "what do you know")],
        provider=provider,
        model="m",
        gateway=_gateway(),
        tools=[],
        sources=[_vector_source()],
        query="what do you know",
        verifier_tools=True,
    )
    assert "Independent verification lookup" in provider.critic_system
    assert "doc fact" in provider.critic_system  # the fresh evidence reached the critic


def test_critic_skips_lookup_in_accurate_mode_verifier_does_it() -> None:
    # In ACCURATE mode the verifier is the last judge and does the lookup, so the critic must NOT
    # also run one (exactly one independent lookup per turn — no redundant work on local serving).
    provider = _CapturingCritic()
    _drain(
        messages=[ChatMessage(Role.USER, "what do you know")],
        provider=provider,
        model="m",
        gateway=_gateway(),
        tools=[],
        sources=[_vector_source()],
        query="what do you know",
        accuracy_mode="accurate",
        verifier_tools=True,
    )
    assert "Independent verification lookup" not in provider.critic_system


def test_tool_armed_verifier_runs_an_independent_lookup() -> None:
    # Tool-armed verifier (#465): in accurate mode with verifier_tools on and sources present, the
    # verifier runs ONE fresh retrieval and folds it into the judging context as an independent
    # "ground truth" block -- catching plausible-but-wrong drafts the consistency check misses.
    provider = _CapturingVerifier()
    _drain(
        messages=[ChatMessage(Role.USER, "what do you know")],
        provider=provider,
        model="m",
        gateway=_gateway(),
        tools=[],
        sources=[_vector_source()],
        query="what do you know",
        accuracy_mode="accurate",
        verifier_tools=True,
    )
    assert "Independent verification lookup" in provider.verifier_system
    assert "doc fact" in provider.verifier_system  # the fresh evidence reached the judge


def test_verifier_tools_off_does_no_independent_lookup() -> None:
    # Same accurate-mode verifier, but with verifier_tools off: no independent block is injected.
    provider = _CapturingVerifier()
    _drain(
        messages=[ChatMessage(Role.USER, "what do you know")],
        provider=provider,
        model="m",
        gateway=_gateway(),
        tools=[],
        sources=[_vector_source()],
        query="what do you know",
        accuracy_mode="accurate",
        verifier_tools=False,
    )
    assert "Independent verification lookup" not in provider.verifier_system
