# Tools: the gateway (M5)

PersonalAI can *act* through **tools** — but every tool call passes through one **gateway** (the
side-effect chokepoint, ADR-0004). The gateway is where permissions, network egress, schemas,
risk approval, timeouts, and audit are enforced; nothing runs until every gate passes.

## What ships

- **calculator** — safe arithmetic (AST-evaluated, *no code execution*); LOW risk, no permissions.
- **http_fetch** — HTTP GET; requires the **NETWORK** permission and the target host must pass the
  **egress allowlist**; redirects disabled; size/time-limited; HIGH risk (needs approval).
- **web_search** — DuckDuckGo search (pinned to `html.duckduckgo.com`, no API key); requires the
  **NETWORK** permission and passes the **egress allowlist**; MEDIUM risk. Used by the agent loop
  (see [the agent loop guide](./agent.md)).

## Try it (UI)

Open **Settings → Tools**:
1. **calculator** → args `{"expression": "2 + 3 * 4"}` → Run → `14`.
2. **http_fetch** → args `{"url": "https://example.com"}` → Run → *"approval required for
   high-risk tool"*. Tick **approve** + **grant permissions** → now it's refused by the egress
   allowlist unless egress is enabled and the host is allow-listed.

## API

```bash
curl -H "Authorization: Bearer demo" http://127.0.0.1:8765/api/v1/tools          # list manifests
curl -X POST http://127.0.0.1:8765/api/v1/tools/invoke -H "Authorization: Bearer demo" \
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
4. **Input** validated against the manifest's JSON Schema. Before a hard rejection, a
   **schema-driven auto-fix** repairs common model slips (see below) and re-validates.
5. **Egress** — any declared network host must pass the egress allowlist (`assert_egress_allowed`).
   Egress is off by default; enabling it with an **empty allowlist denies all hosts** (fail-closed).
   Set `PERSONALAI_ALLOWED_EGRESS_HOSTS`, or opt into open egress with
   `PERSONALAI_EGRESS_ALLOW_ANY=true`. Egress is now enforced **per-tenant**: a tenant's saved
   `egress_enabled` + `allowed_egress_hosts` (Settings → Network) overlay the boot config for that
   turn. See [Network egress](#network-egress-per-tenant) below.
6. **Execute** via the executor with a **timeout**.
7. **Output** validated against the manifest's JSON Schema.
8. **Audit** — every outcome (allowed/denied) is recorded (redacted).

## Schema-driven tool-arg auto-fix

Models often get tool arguments *almost* right. Rather than reject the call (and waste a turn), the
gateway makes a **best-effort, schema-driven repair** before validating, then **re-validates** — so a
wrong guess is still rejected, never silently used. The fixes (read straight from the tool's JSON
Schema, so they apply to **any** tool including MCP):

- **Rename one mislabeled argument** — if exactly one required field is missing and exactly one extra
  field is present, the extra is renamed to the missing one (e.g. `input` → the required `query`).
- **Coerce toward the declared type** — scalar → array (`"http://x"` → `["http://x"]`),
  numeric-string → number (`"5"` → `5`), number → string, and `"true"`/`"false"` → boolean.
- **Clamp numbers** to the schema's `minimum`/`maximum`.

If repair still fails, the **denial message lists the valid parameters** — and for an **enum**
error, the **allowed values** — so the model can self-correct on its next turn.

## Network egress (per-tenant)

Outbound access from in-process tools (and remote model providers) is governed by the egress
allowlist, now applied **per tenant**: each turn overlays the tenant's saved `egress_enabled` +
`allowed_egress_hosts` (Settings → Network) onto the boot config. Hosts are bare lowercase hostnames
(no scheme/path); an enabled-but-empty allowlist still denies all hosts (fail-closed).

When a tool is blocked by egress, the reasoning pane offers a one-click **"allow this host from now
on"**: it calls `POST /api/v1/settings/egress/allow {"host": "<bare hostname>"}`, which **enables
egress and appends the host** to the tenant's allowlist, after which you re-send the request.

## The manifest

Each tool declares a `ToolManifest`: provenance, version, capabilities, least-privilege
`permissions`, JSON-Schema `inputs`/`outputs`, allowed `egress` hosts (empty = none), `risk`
(unverified tools default to HIGH), and optional `integrity` for pinning.

## Execution & sandbox tiers (ADR-0007)

Tools run behind a `ToolExecutor` seam:

- **Tier 0 — in-process (now):** trusted first-party tools, time-bounded, fail-closed.
- **Tier 1 — subprocess (M7):** the default for spawning MCP servers over stdio.
- **Tier 2 — container/microVM (M7+):** untrusted/heavy MCP servers (e.g. Playwright) and
  multi-user worker pools.

Adding a tier is a new adapter behind the port — the gateway and tools are unchanged.

## Add a tool

1. Write a `ToolHandler` (`async invoke(call) -> ToolResult`) in an adapter package that depends
   only on `personalai_contracts`.
2. Declare a `ToolManifest` (permissions, JSON-Schema I/O, egress, risk).
3. Register `RegisteredTool(manifest, handler)` in the composition root.

That's it — the gateway enforces everything else. Third-party **MCP servers** (M7) plug into the
same gateway as tool sources, sandboxed via tier 1/2.
