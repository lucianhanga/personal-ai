# Using MCP servers (M7)

PersonalAI is an **MCP client**: it can connect to published [Model Context
Protocol](https://modelcontextprotocol.io) servers, pull in **their** tools, and let the agent use
them — all through the same **gateway** (permissions, egress allowlist, schema validation, risk
approval, audit) as built‑in tools. Third‑party MCP servers are treated as **untrusted**: their
tools default to **HIGH risk**, so the agent needs your approval to run them.

## Configure a server

Create an `mcp.json` using the standard `mcpServers` map (the same shape Claude Desktop uses) and
point PersonalAI at it:

```json
{
  "mcpServers": {
    "playwright": { "command": "npx", "args": ["-y", "@playwright/mcp@latest"] }
  }
}
```

```bash
PERSONALAI_AUTH_TOKEN=demo PERSONALAI_MCP_CONFIG=./mcp.json make run-backend
```

On startup the backend connects each enabled server, lists its tools, and registers them behind the
gateway. Connection is **best‑effort**: a server that fails to launch is recorded (see below) and
skipped — the app still runs. Add `"enabled": false` to a server to keep it defined but not connect.

**Prerequisites:** servers run in their own runtime. The Playwright MCP is a Node package, so it
needs **Node/`npx`** on the machine (`npx -y @playwright/mcp@latest`). Python servers run via
`uvx`/`pipx`. PersonalAI itself only needs the `mcp` Python SDK (already a dependency).

## Use it

1. Open the **MCP** panel (right sidebar) to confirm the server connected and see its tools.
2. The server's tools appear in the **Tools** panel and are namespaced `server.tool`
   (e.g. `playwright.browser_navigate`).
3. In chat, turn on **Use tools** and **approve high‑risk** (MCP tools are HIGH risk), then ask —
   e.g. *"Open example.com and take a screenshot."* The agent calls the MCP tool through the gateway
   and streams the result.

## Inspect

- `GET /api/v1/mcp` — configured servers, connect status, and the tools each exposed.
- Every MCP call (allowed or denied) is in the per‑chat **Activity** log, and connect/list events in
  **App logs**.

## Security

- MCP servers run **out‑of‑process** (stdio subprocess = sandbox tier 1, ADR‑0007); untrusted/heavy
  servers move to a container tier later.
- All MCP tool calls go through the gateway: **HIGH‑risk approval**, least‑privilege permissions,
  egress allowlist (for HTTP servers), JSON‑Schema validation, timeout, and audit.
- Tool **output is untrusted data**, never instructions (same guard as RAG/web search).

## Verify against a real server (opt‑in)

```bash
PERSONALAI_MCP_IT=1 uv run pytest tools/mcp/tests/test_integration.py -q
```
(Skipped in CI; needs Node/`npx` and network for the first `@playwright/mcp` fetch. Override the
server with `PERSONALAI_MCP_IT_CMD` / `PERSONALAI_MCP_IT_ARGS`.)
