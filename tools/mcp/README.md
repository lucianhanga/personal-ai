# personalai-tool-mcp

MCP client adapter (M7). Connects to [Model Context Protocol](https://modelcontextprotocol.io)
servers (stdio now; Streamable HTTP next), lists their tools, and exposes each as a
`RegisteredTool` behind the PersonalAI **tool gateway** — so MCP tools get the same permissions,
egress allowlist, JSON-Schema validation, risk approval, timeout, and audit as built-in tools.

Depends only on `personalai-contracts` and the official `mcp` SDK (ADR-0001). Third-party MCP
servers are treated as **untrusted** (manifest risk defaults HIGH) and run sandboxed via the
executor tiers (ADR-0007).
