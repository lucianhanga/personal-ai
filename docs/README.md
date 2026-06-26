# PersonalAI Documentation

Start here:

- **[Architecture report](./architecture/PersonalAI-Architecture-Research.md)** — the full
  high-level architecture (22 sections): components, model runtime strategy, agents, tools/MCP,
  structured outputs, omni-capability, storage, security, UI/UX, browser extension, backend,
  deployment, stack, roadmap, risks, open questions, sources.
- **[ADRs](./architecture/adr/)** — Architecture Decision Records.
- **[Threat model](./architecture/THREAT-MODEL.md)** — trust boundaries and threats (v1).
- **[Onboarding / dev guide](./ONBOARDING.md)** — how to work in this repo.
- **[Local chat guide (M1)](./guides/local-chat.md)** — run streaming chat over local Ollama models.
- **[Remote / frontier providers (M2)](./guides/remote-providers.md)** — opt into OpenAI-compatible
  providers (OpenAI/Azure/vLLM/...) with egress + secrets controls.
- **[Files + RAG (M3)](./guides/files-and-rag.md)** — ingest documents, chat with citations, and
  persistent conversation history (PostgreSQL + pgvector).
- **[Documents & folders (Documents v2)](./guides/documents-and-folders.md)** — continuously-synced
  local folders, on-device OCR for scanned PDFs, and the browsable knowledge graph of your entities.
- **[Memory (M4)](./guides/memory.md)** — short-term per-chat summary + cross-chat long-term memory
  you can visualize, edit, and erase; incognito chats.
- **[Tools (M5)](./guides/tools.md)** — the Tool/MCP gateway: permissions, egress allowlist,
  schema-validated I/O, risk approval, audit; built-in calculator + http_fetch.
- **[The agent loop (M6)](./guides/agent.md)** — autonomous tool use (calculator, web search) with
  streamed reasoning + answer, ordered per-message details, all through the gateway.
- **[Using MCP servers (M7)](./guides/mcp.md)** — connect published MCP servers (e.g. Playwright)
  via an `mcp.json`; their tools run through the gateway and the agent can use them.
- **[Settings (M8.2)](./guides/settings.md)** — per-tenant preferences (models, agent mode, memory,
  egress, timeout, embeddings) that overlay the boot config; the Settings view panels and the API.

Reference & development:

- **[Contracts & ports reference](./reference/contracts-and-ports.md)** — every port, value object,
  and reference fake (M0-2), plus the "how to add an adapter" seam workflow.
- **[Structured-output schemas reference](./reference/structured-output-schemas.md)** — the M0-3
  schema backbone: strict/versioned models, the five contracts, the schema registry, the canonical
  JSON Schema + drift test, and the TS/Zod bindings kept aligned by shared fixtures.
- **[Dependency injection & registries](./reference/dependency-injection.md)** — registries,
  config-driven selection, the composition root, and how to register an adapter (M0-4).
- **[Backend API (loopback)](./reference/backend-api.md)** — running the backend, the versioned
  `/api/v1` endpoints, the chat SSE protocol, and the security posture (loopback, auth, origin
  allowlist, egress fail-closed).
- **[Coding standards & conventions](./development/coding-standards.md)** — dependency direction,
  structured-output-first, typing, async, testing/coverage policy.
- **[Toolchain & monorepo](./development/toolchain.md)** — uv + pnpm workspaces, Makefile targets,
  and CI jobs.
- **[Releasing & signing](./development/releasing.md)** — Sigstore/cosign signing, SBOM attachment,
  verification, and the reproducible-build note (M0-9).
- **[Changelog](../CHANGELOG.md)** — versioning policy (pre-1.0 semver in `VERSION`; one MINOR per
  milestone) and the per-release history. The HTTP API is versioned independently as `/api/v1`.

Policies & supply chain:

- **[Dependency policy](./policies/DEPENDENCY-POLICY.md)** — provenance, verification, SBOM, scanning.
- **[Supply-chain register](./supply-chain/SUPPLY-CHAIN.md)** — living inventory of every dependency + creator.

Top-level governance (repo root):

- [README](../README.md) · [SECURITY](../SECURITY.md) · [CONTRIBUTING](../CONTRIBUTING.md) ·
  [CHANGELOG](../CHANGELOG.md) · [LICENSE](../LICENSE)
