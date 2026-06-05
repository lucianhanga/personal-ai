# Architecture Decision Records (ADRs)

This directory records significant architecture decisions, one file per decision, using a
lightweight [MADR](https://adr.github.io/madr/)-style format.

| ADR | Title | Status |
|---|---|---|
| [0001](./0001-modular-monolith-hexagonal.md) | Modular monolith with hexagonal (ports & adapters) architecture | Accepted |
| [0002](./0002-local-first-ollama-default.md) | Local-first with Ollama as default runtime behind a provider abstraction | Accepted |
| [0003](./0003-structured-output-first.md) | Structured-output-first communication (JSON Schema + Pydantic/Zod) | Accepted |
| [0004](./0004-tool-mcp-gateway-sandbox.md) | All side effects via a sandboxed Tool/MCP gateway | Accepted |
| [0005](./0005-postgres-pgvector-storage.md) | PostgreSQL + pgvector as the storage/retrieval spine | Accepted |
| [0006](./0006-ui-react-tauri.md) | UI: React SPA wrapped by a Tauri desktop shell | Accepted |

> New decisions get the next number. Status: Proposed → Accepted → Superseded (link the successor).
