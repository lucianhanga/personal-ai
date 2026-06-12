# 12. Adopt LangGraph as the agent orchestration platform

- Status: Accepted
- Date: 2026-06-12
- Supersedes: ADR-0011 (hand-rolled typed graph)

## Context

ADR-0011 chose a hand-rolled typed state-machine graph for M8, reasoning that the two things a
framework usually sells — provider portability and tool safety — are already owned by our seams
(`ModelProvider`, `ToolGateway`), so any framework would have to be *bent* to call them. That logic
is sound but it traded away maturity, ecosystem, tooling, and — concretely — the exact M8.1/M8.2
primitives we were about to build by hand: durable checkpointing (interrupt/resume), human-in-the-loop
gates, conditional-edge routing, and supervisor/multi-agent patterns.

Product-owner direction (2026-06-12): use a **well-established platform** for the agentic layer and
do not reinvent the wheel; the longer-term vision includes selectable orchestration patterns and,
eventually, user-defined agent graphs. Both points argue for adopting a real graph platform rather
than growing a bespoke one.

## Decision

Adopt **LangGraph** as the multi-agent orchestration engine, superseding ADR-0011's hand-rolled
graph. LangChain is already an approved vendor in the dependency policy, so this crosses no new
supply-chain line of principle (only added surface area, see Consequences).

### Load-bearing invariant (carried over from ADR-0011, unchanged)

LangGraph is used as the **orchestration engine only** — graph topology, typed shared state, the
checkpointer, and `interrupt()`/resume. Our seams remain authoritative for the two privileged
capabilities:

- **Model.** Graph nodes call our `ModelProvider` (Ollama / local-first) **directly**. We do *not*
  adopt LangChain's chat-model abstraction.
- **Tools / MCP.** Graph nodes call our `ToolGateway` **directly** — permissions, egress/SSRF guard,
  schema validation, HIGH-risk approval, tool-output injection envelope, redacted audit all still
  apply. We do *not* adopt LangChain's tool abstraction.

The graph runtime gets no model or tool privileges of its own. This is what keeps the hexagonal
guarantees (ADR-0001), tenant isolation (ADR-0010), and the local-first posture intact while gaining
a mature engine. Because LangGraph nodes are plain async functions, satisfying this invariant is
nearly free: a node is a function that calls our provider and/or gateway and writes typed state.

### Placement (hexagonal)

- LangGraph graphs live in `personalai_core` (the orchestration layer, where `run_agent` and the
  gateway already live). `langgraph` (and its checkpoint library) become **`core` dependencies**.
  No new adapter package; the import-linter contracts (keyed on our own root packages) are unaffected.
- `core.run_graph(...)` keeps its current signature; its body becomes a compiled LangGraph graph.
  `apps/backend/.../turn.py` and the `agent_graph_enabled` flag are unchanged — the backend still
  calls `run_graph` when the flag is on and `run_agent` when it is off.
- The hand-rolled `core/graph.py` (M8.0) is replaced by the LangGraph implementation behind the same
  flag. Parity step first: a single responder graph that equals `run_agent`, ~100% covered.

### Reference shape (unchanged from ADR-0011, now expressed in LangGraph)

- **Nodes:** planner -> researcher (tool-using; today's `run_agent` loop as one node) -> critic ->
  verifier. **Conditional edges** implement the accuracy ladder: schema-check -> conditional
  LLM-judge -> ground-truth -> human gate.
- **Shared typed `AgentState`** maps to the streamed, append-only `meta.trace`, so the UI keeps
  showing reasoning/tool/critic steps in order. LangGraph's streaming feeds the SSE mapping.
- **Accuracy-mode** is conditional edges in one compiled graph (not a separate pipeline).
- **Tenant** travels in the graph state (`AgentContext`, ADR-0010 / A2), not only an ambient
  contextvar.

### Durable interrupt / resume (the human gate) — tenant-safe

LangGraph's **checkpoint is the durable state**, replacing the hand-rolled `pending_runs` table from
the M8 primitives design. The security requirements from that design carry over verbatim and become
the acceptance gate for M8.1:

- Checkpoints MUST be persisted **tenant-scoped under RLS** through our `TenantDb` unit-of-work, so
  agent state gets the same isolation as every domain table (ADR-0010). Preferred mechanism: a thin
  custom `BaseCheckpointSaver` over `TenantDb`. Documented fallback if that proves heavy: LangGraph's
  Postgres saver plus an explicit app-level tenant guard on resume.
- `thread_id = run_id` (uuid). On `POST /api/v1/chat/{run_id}/resume`, a **fresh** `SecurityContext`
  is resolved; the checkpoint loads **only under the resumer's tenant** (RLS) — a thread owned by
  another tenant is simply not found. Belt-and-suspenders: assert `state.tenant_id == ctx.tenant_id`.
- **Cross-tenant resume must be impossible.** A required cross-tenant-resume test is the M8.1
  acceptance gate (closes the same risk #1 the primitives note flagged).
- Replay/double-resume and expiry/GC remain fail-closed (status + expiry; expired runs are dropped,
  never auto-approved).

### Selectable patterns and user-defined graphs

A "pattern" is a compiled graph selected by name; LangGraph makes this a registry of graphs rather
than bespoke plumbing. User-defined agent networks (config- or Studio-authored) become a later
milestone built on the same engine — explicitly **not** in M8 scope, but no longer something we would
have to invent from scratch.

## Consequences

- **Added supply-chain surface.** `langgraph` pulls `langchain-core` (the dependency tree ADR-0011
  wanted to avoid in a now-public repo). Accepted as a deliberate maturity-over-minimalism trade.
  Mitigations: keep the LangChain *usage* surface tiny (engine only, our seams for model+tools), pin
  versions, run it through the existing dependency-policy / supply-chain review, and keep it isolated
  to `core`.
- **The PydanticAI fallback in ADR-0011 is retired** as the primary fallback; if LangGraph proves a
  poor fit, re-evaluate then. The hexagonal seams mean a future engine swap stays contained to
  `core/graph.py` plus the checkpointer.
- M8.0's hand-rolled `core/graph.py` and its tests are rebuilt on LangGraph; `run_graph`'s public
  contract and the `agent_graph_enabled` flag are preserved, so callers (`turn.py`, SSE) are
  unaffected.
- This work stays sequenced after the IAM milestone, so multi-agent state is tenant-aware from the
  start (per ADR-0010), now enforced at the checkpoint layer.
- Defers: distributed/durable execution across hosts (LangGraph supports it, but out of scope until
  multi-process agent execution is a requirement); user-defined graphs (later milestone).
