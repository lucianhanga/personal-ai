# 9. MCP isolation posture: out-of-process servers + gateway envelope; container executor deferred

- Status: Accepted
- Date: 2026-06-10
- Supersedes scope of: #143 (executor-tier prep) and #150 (executor tiers + sandbox for untrusted MCP)

## Context

ADR-0004 (gateway) and ADR-0007 (executor tiers) anticipated running untrusted third-party MCP
servers (e.g. Playwright, Tavily, MarkItDown) and proposed escalating tool execution from the
in-process tier (tier 0) to subprocess (tier 1) and container (tier 2). M7 then actually shipped MCP
support, which changes the calculus: we now know *how* MCP servers run in practice, so we can decide
the isolation posture from evidence rather than speculation.

Key fact: **an MCP server is already a separate process.** PersonalAI is an MCP *client*. A `command`
server runs as its own **stdio subprocess** (its own memory/FDs, killed on disconnect); a remote
server runs over **Streamable HTTP** in someone else's runtime. PersonalAI only holds a thin
`McpToolHandler` that proxies a call over a queue to the owning session. Running that proxy handler
inside a PersonalAI-side container would **not** sandbox the actual server — the server is already
elsewhere. Tools like `@automata-labs-team/code-sandbox-mcp` go further and **self-containerize**
their workload in Docker.

## Decision

Treat the **out-of-process server boundary + the gateway envelope** as the MCP isolation tier, and
**defer** a PersonalAI-side container executor (ADR-0007 tier 2) until a concrete driver exists
(e.g. first-party *untrusted in-process* tools, or a multi-user/hosted deployment).

What is implemented and constitutes the posture (M7):

- **Process isolation:** MCP servers run as stdio subprocesses or remote HTTP — never in the core
  process. The owner-task model keeps each session on one task (anyio cancel-scope safety).
- **Gateway envelope on every call:** HIGH-risk approval (`approve_tools`), least-privilege
  permissions, JSON-Schema I/O validation, timeout, append-only redacted audit.
- **Manifest trust/provenance:** third-party MCP tools default to `RiskLevel.HIGH`, are namespaced
  `<server>.<tool>`, and carry `provenance.maintainer = mcp:<server>`.
- **Egress control:** the egress allowlist + SSRF guard (private/loopback/metadata IPs) block the
  exfiltration paths a chained/injected instruction would use; remote MCP URLs are egress-gated.
- **Prompt-injection guard:** tool/MCP output is fed back to the model as explicit untrusted DATA.
- **Lifecycle:** dynamic register/unregister (`Registry.unregister`) lets servers connect/disconnect
  live without a restart.

## Consequences

- We do not build Docker/container plumbing for MCP now; the security value would be marginal given
  the above, and `code-sandbox-mcp` already self-sandboxes its execution.
- **Residual risk (accepted, local-first single-user):** a configured stdio server runs with the
  user's privileges (same as any program they launch). This is gated by the per-server "runs a
  program on your machine" confirmation and the HIGH-risk approval. A locked-down container tier and
  per-tool egress namespacing remain a future hardening item (revisit at M11 or when hosting).
- The `ToolExecutor` seam (ADR-0007) stays, so a container/subprocess executor can be added later
  without touching the core — the door is open, just not walked through yet.
- Closes #143 and #150 (their valuable parts — dynamic (un)registration, HIGH-risk default,
  egress/SSRF/injection guards — are shipped; the container tier is deferred with this rationale).
