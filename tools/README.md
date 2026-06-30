# tools/ (extension seam)

Internal tools and MCP adapters. Each is self-contained (manifest + sandboxed handler) and is loaded by the Tool/MCP gateway.

## Rule
This is a **seam** (ADR-0001). Add a capability by dropping a new adapter here, registering it,
and declaring its schema **without** modifying the core. Adapters depend inward on
`personalai_contracts` only and never import sibling adapters.

## Current contents
`builtin` (in-process tools), `mcp` (MCP client adapter), `markitdown-ollama` (document-to-markdown service); `test` holds manual fixtures/scripts, not a packaged adapter.
