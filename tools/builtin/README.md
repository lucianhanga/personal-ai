# tools/builtin (`personalai_tool_builtin`)

Built-in tools that run **behind the Tool gateway** (ADR-0004). Depend only on
`personalai_contracts` (+ httpx); never on core/backend.

- **calculator** — safe arithmetic (AST-evaluated, no code execution); LOW risk, no permissions.
- **http_fetch** — HTTP GET, **NETWORK** permission, host gated by the egress allowlist (injected),
  redirects disabled, size/time-limited; HIGH risk.

The composition root pairs each `*_MANIFEST` + handler into a `RegisteredTool` and registers it.
