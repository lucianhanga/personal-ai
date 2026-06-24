"""Egress-approval gate (#377): the 2nd durable LangGraph gate. When a researcher tool's outbound
call is egress-blocked, the run durably PAUSES (interrupt) and waits for Allow-once / Allow-always /
Don't-allow. On allow the ONE blocked call is retried (egress now passes); prior succeeded tool
calls do NOT re-fire. The gate is engine-agnostic at agent.py (an `egress_blocked` AgentEvent + a
resumable run_agent); graph.py's researcher node catches it and interrupt()s inline.

These are pure-fake (no Postgres): an in-memory checkpointer + a counting gateway prove the
no-duplication invariant and the interrupt/resume cycle. The host injection that makes the retry
pass is modeled here by mutating the egress allowlist between the block and the resume — exactly
what the backend does by setting current_egress before re-invoking the graph."""

from __future__ import annotations

import asyncio

from langgraph.checkpoint.memory import InMemorySaver

from personalai_contracts.ports import (
    AgentContext,
    ChatMessage,
    GenerationRequest,
    GenerationResult,
    Role,
    ToolCall,
    ToolCallRequest,
    ToolResult,
)
from personalai_contracts.schemas.tools import Provenance, RiskLevel, ToolManifest
from personalai_contracts.testing import FakeModelProvider
from personalai_core import (
    EGRESS_ALLOW_ONCE,
    EGRESS_DENY,
    EGRESS_RESUME_DECISION,
    EGRESS_RESUME_FRAME,
    AgentEvent,
    InProcessExecutor,
    Registry,
    ToolGateway,
    run_graph,
)
from personalai_core.gateway import RegisteredTool
from personalai_core.security.audit import AuditLog
from personalai_core.security.egress import EgressBlockedError

# A tool that declares an egress host so the gateway runs its egress check before executing it.
FETCH = ToolManifest(
    name="fetch",
    version="2.1.0",
    provenance=Provenance(maintainer="tests"),
    description="fetch a url",
    risk=RiskLevel.LOW,
    egress=("api.example.com",),
)
CALC = ToolManifest(
    name="calc",
    version="1.0.0",
    provenance=Provenance(maintainer="tests"),
    description="calc",
    risk=RiskLevel.LOW,
)


class _CountingGateway(ToolGateway):
    """Counts how many times each tool actually invokes, to prove the retry never replays prior
    succeeded calls. ``allowed`` is the live egress allowlist the backend injects on an allow."""

    def __init__(self, reg: Registry[RegisteredTool], allowed: set[str]) -> None:
        super().__init__(
            reg,
            InProcessExecutor(),
            audit=AuditLog(),
            egress_check=lambda host: None if host in allowed else _deny(host),
        )
        self.calls: dict[str, int] = {}

    async def invoke(self, call: ToolCall, **kw: object) -> ToolResult:
        self.calls[call.tool] = self.calls.get(call.tool, 0) + 1
        return await super().invoke(call, **kw)  # type: ignore[arg-type]


def _deny(host: str) -> None:
    raise EgressBlockedError(f"host {host!r} is not in the egress allowlist")


class _Fetch:
    name = "fetch"

    async def invoke(self, call: ToolCall) -> ToolResult:
        return ToolResult(ok=True, output={"fetched": call.args.get("url", "")})


class _Calc:
    name = "calc"

    async def invoke(self, call: ToolCall) -> ToolResult:
        return ToolResult(ok=True, output={"result": 42})


class _CalcThenFetchThenAnswer(FakeModelProvider):
    """Researcher turn 1: call calc (succeeds) AND fetch (egress-blocked). Turn 2 (after resume):
    a final answer. The two calls in one turn let us assert calc does NOT re-fire on the retry."""

    def __init__(self) -> None:
        super().__init__(name="scripted")
        self._n = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        if request.tools:  # researcher turn
            self._n += 1
            if self._n == 1:
                return GenerationResult(
                    text="",
                    model=request.model,
                    tool_calls=[
                        ToolCallRequest(name="calc", arguments={"x": 1}),
                        ToolCallRequest(
                            name="fetch", arguments={"url": "https://api.example.com/x"}
                        ),
                    ],
                )
            return GenerationResult(text="all done", model=request.model, usage={"total_tokens": 5})
        return GenerationResult(text="plan/critique", model=request.model)


def _tools() -> list[RegisteredTool]:
    return [RegisteredTool(FETCH, _Fetch()), RegisteredTool(CALC, _Calc())]


def _counting_gateway(allowed: set[str]) -> _CountingGateway:
    reg: Registry[RegisteredTool] = Registry("tool")
    for rt in _tools():
        reg.register(rt.manifest.name, rt)
    return _CountingGateway(reg, allowed)


def _drain(**kwargs: object) -> list[AgentEvent]:
    async def _run() -> list[AgentEvent]:
        return [ev async for ev in run_graph(**kwargs)]  # type: ignore[arg-type]

    return asyncio.run(_run())


def _ctx(subject: str = "subj-1") -> AgentContext:
    return AgentContext(tenant_id="t1", subject_id=subject, conversation_id="c1")


def test_egress_block_suspends_with_egress_approval_payload() -> None:
    # The block surfaces an approval_request whose payload is the egress namespace (reason +
    # blocked_host + tool + args), distinct from the answer gate's approve_answer.
    saver = InMemorySaver()
    first = _drain(
        messages=[ChatMessage(Role.USER, "fetch it")],
        provider=_CalcThenFetchThenAnswer(),
        model="m",
        gateway=_counting_gateway(allowed=set()),  # nothing allowed -> fetch blocks
        tools=_tools(),
        approved=True,
        context=_ctx(),
        checkpointer=saver,
        thread_id="run-egress-1",
        max_iterations=4,
    )
    assert first[-1].type == "approval_request"
    payload = first[-1].output or {}
    assert payload["reason"] == "egress_approval"
    assert payload["blocked_host"] == "api.example.com"
    assert payload["tool"] == "fetch"
    assert payload["args"] == {"url": "https://api.example.com/x"}
    # The server-only resume frame rides in the checkpoint payload (the backend whitelists it out
    # of the client SSE, tested at the API layer) and carries the partial convo + the call to retry.
    assert payload[EGRESS_RESUME_FRAME]["blocked_call"]["name"] == "fetch"
    assert payload["subject_id"] == "subj-1"


def test_allow_once_retries_only_the_blocked_call_no_duplicate_side_effects() -> None:
    # The counting invariant (top risk #1): on an allow-resume the retried call invokes again, but a
    # prior succeeded call (calc) does NOT re-fire.
    saver = InMemorySaver()
    allowed: set[str] = set()
    gw = _counting_gateway(allowed)
    common: dict[str, object] = {
        "messages": [ChatMessage(Role.USER, "fetch it")],
        "provider": _CalcThenFetchThenAnswer(),
        "model": "m",
        "gateway": gw,
        "tools": _tools(),
        "approved": True,
        "context": _ctx(),
        "checkpointer": saver,
        "thread_id": "run-once-1",
        "max_iterations": 4,
    }
    first = _drain(**common)
    assert first[-1].type == "approval_request"
    assert gw.calls == {"calc": 1, "fetch": 1}  # both ran once; fetch was denied at egress

    # The backend injects the host into the effective egress before resuming (modeled by allowing it
    # now), then resumes with the egress verb + the checkpointed frame.
    allowed.add("api.example.com")
    resume_frame = (first[-1].output or {})[EGRESS_RESUME_FRAME]
    second = _drain(
        **common,
        resume={EGRESS_RESUME_DECISION: EGRESS_ALLOW_ONCE, EGRESS_RESUME_FRAME: resume_frame},
    )
    # calc did NOT re-fire (still 1); fetch retried once more (now 2). No duplicated side effects.
    assert gw.calls == {"calc": 1, "fetch": 2}
    # The retried fetch reconciles into a successful tool_result on resume.
    fetch_results = [e for e in second if e.type == "tool_result" and e.tool == "fetch"]
    assert fetch_results and fetch_results[-1].ok is True
    # Having cleared the egress gate, the turn proceeds to the ANSWER gate (the other durable gate)
    # — proof the egress gate resolved and the run advanced. Approving it reaches the final.
    assert second[-1].type == "approval_request"
    assert (second[-1].output or {})["reason"] == "approve_answer"
    third = _drain(**common, resume="approve")
    assert any(e.type == "final" for e in third)
    assert gw.calls == {"calc": 1, "fetch": 2}  # still no re-fire through the answer gate


def test_deny_resumes_with_the_egress_error_and_completes() -> None:
    # Don't-allow: the retried call yields the egress error (today's behavior); the turn finishes.
    saver = InMemorySaver()
    gw = _counting_gateway(allowed=set())  # stays blocked through the resume
    common: dict[str, object] = {
        "messages": [ChatMessage(Role.USER, "fetch it")],
        "provider": _CalcThenFetchThenAnswer(),
        "model": "m",
        "gateway": gw,
        "tools": _tools(),
        "approved": True,
        "context": _ctx(),
        "checkpointer": saver,
        "thread_id": "run-deny-1",
        "max_iterations": 4,
    }
    first = _drain(**common)
    resume_frame = (first[-1].output or {})[EGRESS_RESUME_FRAME]
    second = _drain(
        **common,
        resume={EGRESS_RESUME_DECISION: EGRESS_DENY, EGRESS_RESUME_FRAME: resume_frame},
    )
    # Deny: the retried fetch yields the egress error (today's behavior), and the turn advances past
    # the egress gate to the answer gate. Approving it reaches the final.
    fetch_results = [e for e in second if e.type == "tool_result" and e.tool == "fetch"]
    assert fetch_results and fetch_results[-1].ok is False
    assert "egress" in (fetch_results[-1].error or "")
    assert second[-1].type == "approval_request"
    assert (second[-1].output or {})["reason"] == "approve_answer"
    third = _drain(**common, resume="approve")
    assert any(e.type == "final" for e in third)


def test_ungated_graph_degrades_to_nonblocking_egress_error() -> None:
    # No checkpointer (e.g. automated /assistant/execute runs): the gate cannot suspend, so a block
    # degrades to today's behavior — the call yields the egress error and the loop continues, never
    # crashing on interrupt() (which requires a checkpointer).
    events = _drain(
        messages=[ChatMessage(Role.USER, "fetch it")],
        provider=_CalcThenFetchThenAnswer(),
        model="m",
        gateway=_counting_gateway(allowed=set()),
        tools=_tools(),
        approved=True,
        context=_ctx(),
        max_iterations=4,
    )
    assert any(e.type == "final" for e in events)
    assert not any(e.type == "approval_request" for e in events)
    fetch_results = [e for e in events if e.type == "tool_result" and e.tool == "fetch"]
    assert fetch_results and fetch_results[-1].ok is False
