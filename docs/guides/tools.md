# Tools: the gateway (M5)

PersonalAI can *act* through **tools** — but every tool call passes through one **gateway** (the
side-effect chokepoint, ADR-0004). The gateway is where permissions, network egress, schemas,
risk approval, timeouts, and audit are enforced; nothing runs until every gate passes.

## What ships

- **calculator** — safe arithmetic (AST-evaluated, *no code execution*); LOW risk, no permissions.
- **http_fetch** — HTTP GET; requires the **NETWORK** permission and the target host must pass the
  **egress allowlist**; redirects disabled; size/time-limited; HIGH risk (needs approval).

## Try it (UI)

Open the **Tools** panel:
1. **calculator** → args `{"expression": "2 + 3 * 4"}` → Run → `14`.
2. **http_fetch** → args `{"url": "https://example.com"}` → Run → *"approval required for
   high-risk tool"*. Tick **approve** + **grant permissions** → now it's refused by the egress
   allowlist unless egress is enabled and the host is allow-listed.

## API

```bash
curl -H "Authorization: Bearer demo" http://127.0.0.1:8765/api/tools          # list manifests
curl -X POST http://127.0.0.1:8765/api/tools/invoke -H "Authorization: Bearer demo" \
  -H "Content-Type: application/json" \
  -d '{"tool":"calculator","version":"1.0.0","args":{"expression":"2+3*4"}}'
# http_fetch needs the grant + approval (then the egress allowlist applies):
#   "grants":[{"type":"network","scope":"*"}], "approved":true
```

## How the gateway enforces (in order, fail-closed)

1. **Lookup** the tool; **version** must match the manifest (pinning).
2. **Risk approval** — HIGH/CRITICAL tools require an explicit `approved` flag.
3. **Permissions** — every manifest permission must be granted (a grant matches by type and exact
   scope, or scope `*`); least-privilege, deny-by-default.
4. **Input** validated against the manifest's JSON Schema.
5. **Egress** — any declared network host must pass the egress allowlist (`assert_egress_allowed`).
6. **Execute** via the executor with a **timeout**.
7. **Output** validated against the manifest's JSON Schema.
8. **Audit** — every outcome (allowed/denied) is recorded (redacted).

## The manifest

Each tool declares a `ToolManifest`: provenance, version, capabilities, least-privilege
`permissions`, JSON-Schema `inputs`/`outputs`, allowed `egress` hosts (empty = none), `risk`
(unverified tools default to HIGH), and optional `integrity` for pinning.

## Execution & sandbox tiers (ADR-0007)

Tools run behind a `ToolExecutor` seam:

- **Tier 0 — in-process (now):** trusted first-party tools, time-bounded, fail-closed.
- **Tier 1 — subprocess (M6):** the default for spawning MCP servers over stdio.
- **Tier 2 — container/microVM (M6+):** untrusted/heavy MCP servers (e.g. Playwright) and
  multi-user worker pools.

Adding a tier is a new adapter behind the port — the gateway and tools are unchanged.

## Add a tool

1. Write a `ToolHandler` (`async invoke(call) -> ToolResult`) in an adapter package that depends
   only on `personalai_contracts`.
2. Declare a `ToolManifest` (permissions, JSON-Schema I/O, egress, risk).
3. Register `RegisteredTool(manifest, handler)` in the composition root.

That's it — the gateway enforces everything else. Third-party **MCP servers** (M6) plug into the
same gateway as tool sources, sandboxed via tier 1/2.
