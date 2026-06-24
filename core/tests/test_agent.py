"""Single-agent tool-calling loop (fakes only)."""

from __future__ import annotations

import asyncio

from personalai_contracts.ports import (
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
from personalai_core import InProcessExecutor, RegisteredTool, Registry, ToolGateway, run_agent
from personalai_core.agent import AgentEvent
from personalai_core.security.audit import AuditLog

CALC = ToolManifest(
    name="calculator",
    version="1.0.0",
    provenance=Provenance(maintainer="tests"),
    description="math",
    risk=RiskLevel.LOW,
)


class _Calc:
    name = "calculator"

    async def invoke(self, call: ToolCall) -> ToolResult:
        return ToolResult(ok=True, output={"result": 437})


class _Scripted(FakeModelProvider):
    """First turn asks for the calculator; after seeing results, gives a final answer."""

    def __init__(self) -> None:
        super().__init__(name="scripted")
        self._n = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self._n += 1
        if self._n == 1:
            return GenerationResult(
                text="",
                model=request.model,
                tool_calls=[ToolCallRequest(name="calculator", arguments={"expression": "23*19"})],
            )
        return GenerationResult(text="The answer is 437.", model=request.model)


def _gateway() -> ToolGateway:
    reg: Registry[RegisteredTool] = Registry("tool")
    reg.register("calculator", RegisteredTool(CALC, _Calc()))
    return ToolGateway(reg, InProcessExecutor(), audit=AuditLog(), egress_check=lambda h: None)


def test_agent_calls_tool_then_answers() -> None:
    async def _run() -> list[AgentEvent]:
        gw = _gateway()
        tools = [RegisteredTool(CALC, _Calc())]
        return [
            ev
            async for ev in run_agent(
                messages=[ChatMessage(Role.USER, "what is 23*19?")],
                provider=_Scripted(),
                model="m",
                gateway=gw,
                tools=tools,
            )
        ]

    events = asyncio.run(_run())
    kinds = [e.type for e in events]
    # tool turn first (no answer text), then the streamed answer, then final.
    assert kinds == ["tool_call", "tool_result", "answer", "final"]
    assert events[0].tool == "calculator"
    assert events[1].ok is True and events[1].output == {"result": 437}
    # The answer streams as "answer" deltas and is repeated on the final event.
    answer = "".join(e.answer or "" for e in events if e.type == "answer")
    assert answer == "The answer is 437."
    assert events[-1].answer == "The answer is 437."


class _NarratingScripted(FakeModelProvider):
    """Turn 1 narrates its tool use AND calls a tool; turn 2 gives the final answer."""

    def __init__(self) -> None:
        super().__init__(name="narrate")
        self._n = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self._n += 1
        if self._n == 1:
            return GenerationResult(
                text="Let me calculate that for you.",
                model=request.model,
                tool_calls=[ToolCallRequest(name="calculator", arguments={"expression": "23*19"})],
            )
        return GenerationResult(text="The answer is 437.", model=request.model)


def test_tool_turn_narration_is_preserved_as_reasoning() -> None:
    # A turn that calls a tool is the model narrating ("let me…"). The narration streams (the
    # consumer drops it from the answer on the tool_call) and is also re-emitted as reasoning so it
    # lands in the trace. The final answer is the post-tool turn's text.
    async def _run() -> list[AgentEvent]:
        return [
            ev
            async for ev in run_agent(
                messages=[ChatMessage(Role.USER, "what is 23*19?")],
                provider=_NarratingScripted(),
                model="m",
                gateway=_gateway(),
                tools=[RegisteredTool(CALC, _Calc())],
            )
        ]

    events = asyncio.run(_run())
    # The narration is preserved as a reasoning event.
    reasoning = next(e for e in events if e.type == "reasoning")
    assert reasoning.thinking == "Let me calculate that for you."
    # Exactly one tool call (the consumer resets the answer on it).
    assert sum(1 for e in events if e.type == "tool_call") == 1
    # The final answer is the post-tool turn's text, not the narration.
    final = next(e for e in events if e.type == "final")
    assert final.answer == "The answer is 437."


def test_agent_answers_directly_without_tools() -> None:
    async def _run() -> list[AgentEvent]:
        return [
            ev
            async for ev in run_agent(
                messages=[ChatMessage(Role.USER, "hi")],
                provider=FakeModelProvider(),
                model="m",
                gateway=_gateway(),
                tools=[RegisteredTool(CALC, _Calc())],
            )
        ]

    events = asyncio.run(_run())
    assert [e.type for e in events] == ["answer", "final"]  # answer streamed, then final
    assert events[0].answer == "echo: hi"
    assert events[-1].answer == "echo: hi"


def test_agent_surfaces_reasoning() -> None:
    class _Thinker(FakeModelProvider):
        async def generate(self, request: GenerationRequest) -> GenerationResult:
            return GenerationResult(text="the answer", model=request.model, thinking="step by step")

    async def _run() -> list[AgentEvent]:
        return [
            ev
            async for ev in run_agent(
                messages=[ChatMessage(Role.USER, "why?")],
                provider=_Thinker(),
                model="m",
                gateway=_gateway(),
                tools=[RegisteredTool(CALC, _Calc())],
                think=True,
            )
        ]

    events = asyncio.run(_run())
    # Reasoning is emitted as its own ordered event (before the final answer).
    assert events[0].type == "reasoning"
    assert events[0].thinking == "step by step"
    assert events[-1].type == "final"


def test_agent_forces_answer_after_cap() -> None:
    """At the tool-step cap, a final tools-disabled turn must still produce a streamed answer."""

    class _AlwaysTool(FakeModelProvider):
        async def generate(self, request: GenerationRequest) -> GenerationResult:
            if request.tools:  # budget remains -> keep calling the tool (with some chatter)
                return GenerationResult(
                    text="ok",
                    model=request.model,
                    tool_calls=[ToolCallRequest(name="calculator", arguments={})],
                )
            # forced-final turn (tools disabled) -> synthesize an answer (with reasoning + usage)
            return GenerationResult(
                text="Best answer from what I found.",
                model=request.model,
                thinking="wrapping up",
                usage={"total_tokens": 5},
            )

    async def _run() -> list[AgentEvent]:
        return [
            ev
            async for ev in run_agent(
                messages=[ChatMessage(Role.USER, "go")],
                provider=_AlwaysTool(),
                model="m",
                gateway=_gateway(),
                tools=[RegisteredTool(CALC, _Calc())],
                max_iterations=2,
            )
        ]

    events = asyncio.run(_run())
    assert sum(e.type == "tool_call" for e in events) == 2  # used the whole budget
    answer = "".join(e.answer or "" for e in events if e.type == "answer")
    assert "Best answer from what I found." in answer  # forced-final streamed a real answer
    assert events[-1].type == "final" and events[-1].answer == "Best answer from what I found."
    assert events[-1].usage == {"total_tokens": 5}  # usage from the forced-final turn


def test_tool_output_fed_back_as_untrusted_data() -> None:
    """The model's next turn must see the tool result framed as untrusted DATA (injection guard)."""

    class _Capture(FakeModelProvider):
        def __init__(self) -> None:
            super().__init__(name="cap")
            self._n = 0
            self.seen: list[str] = []

        async def generate(self, request: GenerationRequest) -> GenerationResult:
            self._n += 1
            if self._n == 1:
                return GenerationResult(
                    text="", model=request.model, tool_calls=[ToolCallRequest("calculator", {})]
                )
            self.seen = [m.content for m in request.messages if m.role == Role.TOOL]
            return GenerationResult(text="done", model=request.model)

    provider = _Capture()

    async def _run() -> None:
        async for _ in run_agent(
            messages=[ChatMessage(Role.USER, "go")],
            provider=provider,
            model="m",
            gateway=_gateway(),
            tools=[RegisteredTool(CALC, _Calc())],
        ):
            pass

    asyncio.run(_run())
    assert provider.seen and "untrusted DATA" in provider.seen[0]
    assert "<tool_output>" in provider.seen[0]


def test_large_tool_output_is_truncated() -> None:
    from personalai_core.agent import _tool_payload

    payload = _tool_payload(True, {"content": "x" * 50_000}, None)
    assert len(payload) < 50_000 and "truncated" in payload
    assert len(_tool_payload(True, {"content": "small"}, None)) < 100  # short output untouched


# --- Egress-approval gate, engine-agnostic agent layer (#377) ------------------------------------

from personalai_core.agent import (  # noqa: E402 - grouped with the egress-gate tests below
    BlockedCall,
    ResumeFrame,
    deserialize_convo,
    serialize_convo,
)

FETCH = ToolManifest(
    name="fetch",
    version="2.1.0",
    provenance=Provenance(maintainer="tests"),
    description="fetch",
    risk=RiskLevel.LOW,
    egress=("api.example.com",),
)


class _Fetch:
    name = "fetch"

    async def invoke(self, call: ToolCall) -> ToolResult:
        return ToolResult(ok=True, output={"fetched": True})


class _CountingGateway(ToolGateway):
    """A gateway that counts real invocations and denies egress to any host not in ``allowed`` —
    proving (top risk #1) a resume retries ONLY the blocked call, never prior succeeded ones."""

    def __init__(self, allowed: set[str]) -> None:
        from personalai_core.security.egress import EgressBlockedError

        reg: Registry[RegisteredTool] = Registry("tool")
        reg.register("calculator", RegisteredTool(CALC, _Calc()))
        reg.register("fetch", RegisteredTool(FETCH, _Fetch()))

        def _check(host: str) -> None:
            if host not in allowed:
                raise EgressBlockedError(f"host {host!r} is not in the egress allowlist")

        super().__init__(reg, InProcessExecutor(), audit=AuditLog(), egress_check=_check)
        self.calls: dict[str, int] = {}

    async def invoke(self, call: ToolCall, **kw: object) -> ToolResult:
        self.calls[call.tool] = self.calls.get(call.tool, 0) + 1
        return await super().invoke(call, **kw)  # type: ignore[arg-type]


class _CalcThenFetch(FakeModelProvider):
    """One turn requesting BOTH calc (succeeds) and fetch (egress-blocked), then a final answer."""

    def __init__(self) -> None:
        super().__init__(name="cf")
        self._n = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self._n += 1
        if self._n == 1:
            return GenerationResult(
                text="",
                model=request.model,
                tool_calls=[
                    ToolCallRequest(name="calculator", arguments={"x": 1}),
                    ToolCallRequest(name="fetch", arguments={"url": "https://api.example.com/x"}),
                ],
            )
        return GenerationResult(text="done", model=request.model)


def test_egress_block_emits_event_and_returns_without_reprompt() -> None:
    # On an egress-blocked tool result the loop yields a single `egress_blocked` event (carrying the
    # tool, args, parsed host, and the partial convo) and RETURNS — it does not re-prompt the model.
    gw = _CountingGateway(allowed=set())

    async def _run() -> list[AgentEvent]:
        return [
            ev
            async for ev in run_agent(
                messages=[ChatMessage(Role.USER, "fetch it")],
                provider=_CalcThenFetch(),
                model="m",
                gateway=gw,
                tools=[RegisteredTool(CALC, _Calc()), RegisteredTool(FETCH, _Fetch())],
                approved=True,
            )
        ]

    events = asyncio.run(_run())
    blocked = next(e for e in events if e.type == "egress_blocked")
    assert blocked.tool == "fetch"
    assert blocked.args == {"url": "https://api.example.com/x"}
    assert (blocked.output or {})["blocked_host"] == "api.example.com"
    # The loop stopped at the block: no `final`, the calc ran once, fetch was attempted once.
    assert not any(e.type == "final" for e in events)
    assert gw.calls == {"calculator": 1, "fetch": 1}
    # The carried convo already holds the calc TOOL message (partial progress) but NOT a fetch one.
    convo = deserialize_convo((blocked.output or {})["convo"])
    tool_msgs = [m for m in convo if m.role == Role.TOOL]
    assert any("result" in m.content for m in tool_msgs)  # calc's success is recorded
    assert all("fetched" not in m.content for m in tool_msgs)  # fetch never succeeded yet


def test_resume_from_retries_only_the_blocked_call() -> None:
    # The counting invariant: re-entering with a ResumeFrame retries EXACTLY the blocked call and
    # falls into the forward loop; the prior succeeded calc does NOT re-fire.
    gw = _CountingGateway(allowed=set())

    async def _block() -> AgentEvent:
        async for ev in run_agent(
            messages=[ChatMessage(Role.USER, "fetch it")],
            provider=_CalcThenFetch(),
            model="m",
            gateway=gw,
            tools=[RegisteredTool(CALC, _Calc()), RegisteredTool(FETCH, _Fetch())],
            approved=True,
        ):
            if ev.type == "egress_blocked":
                return ev
        raise AssertionError("expected an egress block")

    blocked = asyncio.run(_block())
    assert gw.calls == {"calculator": 1, "fetch": 1}

    # Re-enter with the carried frame, against a gateway whose allowlist now includes the host (what
    # the backend does by injecting it into current_egress). A SEPARATE counter makes the no-refire
    # invariant explicit: only the retried fetch may appear in it; calc must not.
    frame = ResumeFrame(
        convo=deserialize_convo((blocked.output or {})["convo"]),
        blocked_call=BlockedCall(
            name="fetch", version="2.1.0", arguments={"url": "https://api.example.com/x"}
        ),
    )
    gw2 = _CountingGateway(allowed={"api.example.com"})

    class _AnswerNow(FakeModelProvider):
        # The forward turn after the retried call: no more tools, just the final answer.
        async def generate(self, request: GenerationRequest) -> GenerationResult:
            return GenerationResult(text="done", model=request.model)

    async def _resume() -> list[AgentEvent]:
        return [
            ev
            async for ev in run_agent(
                messages=(),
                provider=_AnswerNow(),
                model="m",
                gateway=gw2,
                tools=[RegisteredTool(CALC, _Calc()), RegisteredTool(FETCH, _Fetch())],
                approved=True,
                resume_from=frame,
            )
        ]

    events = asyncio.run(_resume())
    # Only the retried fetch fired on resume; calc never re-fired (it is absent from gw2.calls).
    assert gw2.calls == {"fetch": 1}
    assert "calculator" not in gw2.calls
    retried = next(e for e in events if e.type == "tool_result" and e.tool == "fetch")
    assert retried.ok is True
    assert any(e.type == "final" for e in events)
    # serialize_convo round-trips the carried convo (the checkpointer relies on it).
    assert deserialize_convo(serialize_convo(frame.convo)) == list(frame.convo)


def test_egress_host_parser_only_matches_gateway_denials() -> None:
    # The host parser keys off the gateway's stable ``egress blocked: host=<h>:`` prefix; a plain
    # tool error is NOT mistaken for an egress block (it would wrongly pause the run otherwise).
    from personalai_core.agent import _egress_blocked_host

    assert _egress_blocked_host(False, "egress blocked: host=api.example.com: not allowed") == (
        "api.example.com"
    )
    assert _egress_blocked_host(False, "tool error: boom") is None
    assert _egress_blocked_host(True, None) is None  # a success is never a block
