# 11. M8 agent framework: a hand-rolled typed graph over the existing seams

- Status: Superseded by ADR-0012
- Date: 2026-06-10
- Supersedes: the "LangGraph deferred to M8" part of ADR-0008
- Superseded by: ADR-0012 (adopt LangGraph) — 2026-06-12. The product-owner direction is to use a
  well-established platform rather than a hand-rolled graph. The load-bearing invariant (nodes call
  only our `ModelProvider` + `ToolGateway`) and the reference shape (planner/researcher/critic/
  verifier + accuracy ladder) carry forward unchanged; only the engine changes.

## Context

M8 introduces multi-agent orchestration with selective verification: role-specialized agents
(researcher / critic), a tiered factuality ladder (schema → conditional LLM-judge → ground-truth →
human), an accuracy-mode toggle, and shared state — built **above** the existing seams (ADR-0004
gateway, ADR-0002 ModelProvider, registries) without bypassing them. ADR-0008 shipped the M6/M7
single-agent loop (`run_agent`) and deferred the framework choice to here. The agentic-AI architect
scored five options against nine weighted criteria (local-first/Ollama fit, supply-chain weight &
maturity, fit with our gateway/provider seams, human-in-the-loop + checkpointing, streaming + ordered
trace to SSE, structured/typed state, observability, testability to ~100%, learning/maintenance).

## Decision

Build a **hand-rolled, typed state-machine graph** over the existing `ModelProvider` + `ToolGateway`
seams (extending `run_agent` into composable nodes), rather than adopting a third-party agent
framework. **PydanticAI (`pydantic-graph`)** is the explicit fallback if the hand-rolled graph
outgrows itself.

Rationale: the two things a framework would add value for — **provider portability** and **tool
safety** — are already owned by our seams, so any framework must be *bent* to call the gateway +
provider (never get direct model/tool access). LangGraph (scored third) pulls the `langchain-core`
dependency tree, a real supply-chain cost for a **local-first, now-public** repo; the OpenAI Agents
SDK is OpenAI-centric (weak local-first fit); AutoGen is heavier than needed. A small typed graph
keeps full control of streaming, the ordered `meta.trace`, testability with fakes, and the
hexagonal invariant.

### Invariant (load-bearing)
Graph nodes call **only** the seams (`ModelProvider`, `ToolGateway`/MCP); the graph runtime gets no
model or tool privileges of its own. Tool/MCP calls keep going through the gateway (permissions,
egress, SSRF guard, schema, HIGH-risk approval, audit, tool-output injection guard).

### Reference shape
- **Nodes:** planner → researcher (tool-using, today's `run_agent` loop as one node) → critic →
  verifier; conditional edges implement the **accuracy ladder**: schema-always → conditional
  LLM-judge → ground-truth check → **human gate** (reuses the existing HIGH-risk approval UX via a
  durable interrupt).
- **Shared `AgentState`** (typed) maps to the streamed, append-only `meta.trace`, so the UI keeps
  showing reasoning/tool/critic steps in order.
- **Accuracy-mode** is conditional edges in one graph (not a separate pipeline).

### Migration
Flag-gated (`agent.graph_enabled`): the single-agent loop keeps working throughout; the graph is
introduced behind the flag and matured in phases (M8.0–M8.5). New roles/critics are additive nodes.

## Consequences

- No `langchain`/`langgraph` dependency; the agent layer stays light and fully under our control +
  test coverage culture.
- This work is sequenced **after the Identity & multi-tenancy milestone**, so multi-agent state is
  tenant-aware from the start (per ADR-0010) rather than retrofitted.
- If the hand-rolled graph accrues too much orchestration boilerplate, adopt PydanticAI
  `pydantic-graph` (same node model, typed, minimal deps) — a contained switch, not a rewrite.
- Defers: distributed/durable execution engines; revisit only if multi-process agent execution or
  cross-host workflows become a requirement.
