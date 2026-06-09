# Using MCP servers (M7)

PersonalAI is an **MCP client**: it can connect to published [Model Context
Protocol](https://modelcontextprotocol.io) servers, pull in **their** tools, and let the agent use
them — all through the same **gateway** (permissions, egress allowlist, schema validation, risk
approval, audit) as built‑in tools. Third‑party MCP servers are treated as **untrusted**: their
tools default to **HIGH risk**, so the agent needs your approval to run them.

## Configure servers in the UI (no restart)

The simplest way: open **Settings → MCP** in the app and use **+ Add** to enter a server's
name / command / args / env, then **Save**. PersonalAI connects it immediately (no backend
restart), registers its tools behind the gateway, and shows status (connected / tools / errors).
**Connect/Disconnect**, **Edit**, and **✕** (remove) act live. Changes are saved to the same
`mcp.json` file (see below), so the UI and the file stay in sync.

> Adding a server means specifying a **program to run on your machine**, so the UI asks you to
> confirm before connecting. The API is bearer-token-gated and MCP tools stay HIGH-risk
> (approve-high-risk in chat) — see Security.

## Configure a server (file)

You can also edit the config file directly. PersonalAI uses the standard `mcpServers` map (the same
shape Claude Desktop uses), at `PERSONALAI_MCP_CONFIG` or, if unset, `~/.personalai/mcp.json`:

```json
{
  "mcpServers": {
    "playwright": { "command": "npx", "args": ["-y", "@playwright/mcp@latest", "--headless"] }
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

## Example: Playwright + MarkItDown (with local Ollama OCR)

Two useful servers — browser automation and document→Markdown conversion:

```json
{
  "mcpServers": {
    "playwright": { "command": "npx", "args": ["-y", "@playwright/mcp@latest", "--headless"] },
    "markitdown": {
      "command": "uv",
      "args": ["run", "--script", "/ABS/PATH/personalAI/tools/markitdown-ollama/server.py"],
      "env": { "MARKITDOWN_OLLAMA_MODEL": "qwen2.5vl:7b" }
    }
  }
}
```

- **Playwright:** run `npx playwright install chromium` once (browser, ~150 MB). First `npx` run
  downloads the server.
- **MarkItDown + local OCR:** the official `markitdown-mcp` does plain conversion only and can't use
  a local model for image descriptions, so PersonalAI ships a small wrapper —
  [`tools/markitdown-ollama/server.py`](../../tools/markitdown-ollama/README.md) — that points
  MarkItDown's image converter at **Ollama** (no remote services). Pull a vision model first:
  `ollama pull qwen2.5vl:7b` (~6 GB; `qwen2.5vl:32b` for higher quality — both fit alongside the
  chat model on 48 GB). Configure the endpoint/model via `MARKITDOWN_OLLAMA_BASE_URL` /
  `MARKITDOWN_OLLAMA_MODEL` (defaults: `http://localhost:11434/v1`, `qwen2.5vl:7b`).

### Tavily (web search/extract/crawl for agents)

[Tavily](https://github.com/tavily-ai/tavily-mcp) exposes `search`, `extract`, `map`, and `crawl` —
built for agent discovery workflows (search → pick URLs → extract → optionally crawl/map → answer
with sources). Add it like:

```json
"tavily": {
  "command": "npx",
  "args": ["-y", "tavily-mcp@latest"],
  "env": {
    "TAVILY_API_KEY": "<your-tavily-api-key>",
    "DEFAULT_PARAMETERS": "{\"search_depth\":\"advanced\",\"max_results\":8,\"include_raw_content\":false,\"include_images\":false}"
  }
}
```

> **Not private/local.** The MCP server runs locally but Tavily performs **outbound API calls** to
> Tavily's service (and needs a `TAVILY_API_KEY`). For web *discovery* that's expected; if you need
> privacy over discovery quality, a self-hosted **SearXNG** MCP is the alternative.

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
