# ADR-0008: Single-agent tool-calling loop (hand-rolled, streaming)

- Status: Accepted (the "LangGraph deferred to M8" note is **superseded by ADR-0011**, which chose a
  hand-rolled typed graph over LangGraph for M8)
- Date: 2026-06-09
- Related: ADR-0004 (tool gateway), ADR-0007 (executor sandbox tiers), ADR-0011 (M8 agent framework)

## Context

M6 needs an agent that can call tools, read results, reason, and continue to a final answer, with
everything streamed to the UI. Options for the orchestration:

1. A **framework** (LangGraph / OpenAI Agents SDK / AutoGen).
2. A **hand-rolled loop** in the core, calling the existing `ModelProvider` + `ToolGateway` seams.

## Decision

Use a **hand-rolled streaming loop** (`personalai_core.agent.run_agent`) for the single-agent case:

- It consumes `ModelProvider.stream()`, emitting **reasoning** and **answer** deltas live and parsing
  `tool_calls` from the stream; tool calls execute through the **ToolGateway** (ADR-0004); results are
  fed back as TOOL-role messages; it loops to a final answer or a max-iteration cap.
- The loop yields a typed, **ordered** event stream (`reasoning` / `answer` / `tool_call` /
  `tool_result` / `final`) that the backend maps to SSE and persists as the message's `meta.trace`.

Rationale:

- The hard parts (provider portability, tool safety) already live behind our ports; a loop over them
  is small, fully testable with fakes, and adds **no heavy dependency** (local-first, minimal-deps).
- It keeps the **gateway** as the single side-effect chokepoint — the framework would have to be bent
  to honour it anyway.
- Streaming + tool-calling interleaving is straightforward to express directly.

## Consequences

- We own the loop logic (iteration cap, message protocol, ordering). That is intentionally simple.
- **Multi-agent** orchestration (M8) — planner/worker graphs, selective verification, shared state —
  is where a graph framework (e.g. **LangGraph**) earns its keep; adopting one there is deferred to
  M8 and would sit *above* the same gateway/provider seams, not replace them.
- MCP servers (M7) become additional tool sources behind the gateway; the loop is unchanged.
