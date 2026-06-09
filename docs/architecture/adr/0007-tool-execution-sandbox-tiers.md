# 7. Tool execution behind an Executor seam, in-process tier first

- Status: Accepted
- Date: 2026-06-08

## Context

ADR-0004 mandates that all side effects go through one Tool/MCP gateway with tiered sandboxing.
M5 realizes the gateway. We need to decide *how tools actually run* without (a) over-building OS
isolation before it is needed, or (b) painting ourselves into a corner for untrusted third-party
MCP servers (M7, e.g. Microsoft Playwright MCP) or a future multi-user deployment.

## Decision

Put tool execution behind a **`ToolExecutor` port** (the gateway calls the executor; the executor
runs the handler under a time bound and is **fail-closed** — returns a `ToolResult(ok=False)` on
timeout/error, never raises). Ship one tier now and add stronger tiers as drivers appear:

- **Tier 0 — `InProcessExecutor` (now):** runs first-party, trusted built-in tools in-process with
  a timeout. The gateway still enforces permissions, JSON-Schema I/O, egress allowlist, risk
  approval, and audit around it.
- **Tier 1 — subprocess (M7):** resource/network-limited child process; the default for spawning
  **MCP servers over stdio** (which are out-of-process by protocol regardless).
- **Tier 2 — container/microVM (M7+):** strongest isolation for untrusted/heavy MCP servers
  (e.g. a browser-driving Playwright MCP) and the path to multi-user worker pools.

Selecting in-process now does not lock anything in: the gateway, manifests, permission model, and
every caller are unchanged when a new executor tier is added — it is a new adapter behind the same
port plus a config switch.

## Consequences

- Positive: tool-calling ships immediately; the isolation upgrade is additive; untrusted MCP and
  multi-user both have a clear, non-throwaway path (the executor seam).
- Negative: tier 0 offers no OS-level isolation, so only *trusted* code may run in-process; running
  untrusted tools requires tier 1/2, which lands with MCP in M7 (tracked, not optional).

## Alternatives considered

- Subprocess/container from day one — rejected for M5: more plumbing before there is untrusted code
  to isolate (built-ins are first-party); the seam keeps it cheap to add when MCP arrives.
- Hardcoding in-process execution (no seam) — rejected: would force a rewrite to isolate untrusted
  MCP servers and to scale to multi-user.
