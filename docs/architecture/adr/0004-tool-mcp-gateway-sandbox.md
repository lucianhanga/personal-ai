# 4. All side effects via a sandboxed Tool/MCP gateway

- Status: Accepted
- Date: 2026-06-05

## Context

Tools and MCP servers are the primary attack surface (prompt injection → tool misuse →
exfiltration; malicious/insecure MCPs). The MCP spec explicitly does not enforce security at the
protocol level, and the ecosystem has a real CVE history. Security must be enforced by us.

## Decision

Route **all side effects through a single Tool/MCP gateway** — the orchestrator never executes
tools directly. Enforce: **deny-by-default** permissions; per-tool **network egress allowlist**
(default none); **tiered sandboxing** (container → gVisor → microVM/WASM by risk); **human
approval gates** for high-risk actions; **append-only audit** of every call. Each tool/MCP ships
a **manifest** (provenance, version, capabilities, permission scopes, I/O schemas, egress hosts,
risk, signature/hash). Third-party MCPs follow a verification workflow (provenance → license →
pin+hash → review permissions → sandboxed egress-off run → explicit approval). Tools are enabled
per user → workspace → project; most restrictive scope wins.

## Consequences

- Positive: a single auditable chokepoint for danger; least privilege; safe plug-in/out.
- Negative: approval friction (mitigated by remembered per-scope grants); strong sandboxing is
  Linux-centric, so macOS/Windows untrusted-tool isolation is weaker and needs design attention.

## Alternatives considered

- Direct tool calls from agents — rejected (no chokepoint, unsafe).
- Trusting MCP servers by default — rejected (CVE history; spec disclaims security).
