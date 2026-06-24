# PersonalAI

[![CI](https://github.com/lucianhanga/personal-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/lucianhanga/personal-ai/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.8.3-blue.svg)](./CHANGELOG.md)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Status: M8.3 egress gate + transparency panel done](https://img.shields.io/badge/status-M8.3%20done-brightgreen.svg)](./docs/architecture/adr/0013-egress-approval-gate.md)
[![Local-first](https://img.shields.io/badge/local--first-yes-brightgreen.svg)](#principles)
[![Structured-output-first](https://img.shields.io/badge/structured--output--first-yes-brightgreen.svg)](#principles)
[![Security-first](https://img.shields.io/badge/security--first-yes-brightgreen.svg)](./SECURITY.md)
[![Conventional Commits](https://img.shields.io/badge/commits-conventional-blueviolet.svg)](https://www.conventionalcommits.org/)

> A **local-first**, omni-capable AI assistant — like ChatGPT/Claude, but it runs open-source
> models on **your** hardware, works with **your** files and tools, and reaches external
> providers **only** when you explicitly configure and approve it.

PersonalAI is **extensible** (tools + MCP), **structured-output-first** (schemas everywhere),
**open-source-first** (verified provenance only), and **security-first** (zero-trust toward
tools, files, prompts, model outputs, and MCP servers).

**Current state:** the core product works end to end — streaming chat over local or remote models,
chat-with-your-documents (RAG with citations), long-term memory, a security-first tool/MCP gateway,
single- or multi-agent modes with durable human-in-the-loop gates, and always-on multi-tenancy,
behind a two-view UI with a transparency panel. Milestones **M0–M9** have shipped — including
**M9 Multimodal** (vision · speech-to-text · text-to-speech); the most recent work, **M8.3**, added
the blocking egress-approval gate and the transparency panel. The MV3 browser extension (M10) is next.

- **What's new / full history:** [CHANGELOG](./CHANGELOG.md)
- **Roadmap:** [§22 Modular Implementation Roadmap](./docs/architecture/PersonalAI-Architecture-Research.md#22-modular-implementation-roadmap)
- **Learn how it works:** the [How it works](#how-it-works) section below, then the
  [Documentation](#documentation) table.

## Quickstart (local chat)

```bash
make setup
make db                      # local Postgres + pgvector (docker compose)
# terminal 1 — backend (local mode = zero-login; multi-tenancy runs as tenant #1)
PERSONALAI_DEFAULT_MODEL=qwen3:14b make run-backend
# terminal 2 — UI -> http://localhost:5173 (no token needed in local mode)
pnpm --filter @personalai/ui dev
```

Requires a local [Ollama](https://ollama.com) with a model pulled. `app_mode` defaults to **local**
(zero-login dev). For multi-tenant **hosted** mode (real login + cookies + CSRF) set
`PERSONALAI_APP_MODE=hosted`. Full guide: [docs/guides/local-chat.md](./docs/guides/local-chat.md);
all env vars are in [`.env.example`](./.env.example).

---

## Principles

| Principle | Meaning |
|---|---|
| **Local-first, cloud-optional** | Full core works offline; any egress is opt-in, per-provider, and visible. |
| **Structured-output-first** | All agent ↔ backend ↔ tool ↔ UI messages are schema-validated. |
| **Zero-trust I/O** | Files, prompts, model outputs, tool results, and MCP servers are treated as adversarial. |
| **Least privilege + explicit consent** | Tools are off by default; grants are narrow, scoped, and revocable. |
| **Verified provenance** | Every dependency has a known reputable maintainer, license, maturity, and a documented reason. |
| **Portability** | Swap local ↔ remote models and storage backends behind stable interfaces. |
| **Auditable & reproducible** | Append-only audit log, SBOM, signed releases, reproducible builds where feasible. |

---

## How it works

A **single-host modular monolith** (hexagonal: ports & adapters + registries) fronting isolated
runtimes — local model servers and **sandboxed** tools/MCP servers — with security, audit, and
tenant isolation as cross-cutting layers.

**The AI workflow.** Every turn runs in one of two modes, chosen per tenant:

- **Single-agent loop** — one model reasons and calls tools through the gateway until it answers.
- **Multi-agent graph** (LangGraph, ADR-0012) — **planner → researcher → critic**, with a bounded
  reflection loop and an optional verification step.

Both modes share the same security seams:

- **Tool/MCP gateway** — permissions, schema-validated I/O, risk approval, an egress allowlist, and
  an append-only audit log front every tool and MCP server.
- **Two durable human-in-the-loop gates** — an **answer-approval gate** and a **blocking
  egress-approval gate** (ADR-0013) that pause the run durably when a tool reaches a
  non-allowlisted host (allow-once / allow-always / deny / inspect).
- **RAG + memory** — pgvector retrieval over your ingested documents (with citations) plus per-chat
  short-term and cross-chat long-term memory feed the prompt each turn.

Full diagram and rationale: [architecture report](./docs/architecture/PersonalAI-Architecture-Research.md).

### Stack

| Area | Choice |
|---|---|
| Backend | Python (`uv` workspace) + FastAPI, hexagonal modular monolith |
| UI | React + Vite SPA (Tauri shell for desktop) |
| Database / RAG | PostgreSQL + pgvector |
| Model providers | Ollama (local, default) and OpenAI-compatible (remote, opt-in) |
| Agent orchestration | Single-agent loop + opt-in LangGraph multi-agent graph (ADR-0012) |
| Auth / multi-tenancy | argon2id + server sessions + Postgres Row-Level Security (ADR-0010) |
| Schemas | Pydantic / Zod + JSON Schema |

The complete provenance register (maintainer, license, maturity, security notes) lives in
[`SUPPLY-CHAIN.md`](./docs/supply-chain/SUPPLY-CHAIN.md). The full roadmap and milestone status is in
[§22 Modular Implementation Roadmap](./docs/architecture/PersonalAI-Architecture-Research.md#22-modular-implementation-roadmap).

---

## Documentation

**Guides** (how to use it):

| Guide | Purpose |
|---|---|
| [Local chat](./docs/guides/local-chat.md) | Run streaming chat over local Ollama models. |
| [Remote providers](./docs/guides/remote-providers.md) | Use a remote OpenAI-compatible provider (opt-in). |
| [Files + RAG](./docs/guides/files-and-rag.md) | Chat with your documents (ingestion → pgvector RAG). |
| [Memory](./docs/guides/memory.md) | Short-term and long-term memory (view/edit/erase). |
| [Tools](./docs/guides/tools.md) | Built-in tools and the gateway. |
| [Agent loop](./docs/guides/agent.md) | Single- and multi-agent modes. |
| [MCP servers](./docs/guides/mcp.md) | Plug in / manage MCP servers. |
| [Settings](./docs/guides/settings.md) | Per-tenant settings (model, agent, egress, timeout). |

**Project & architecture:**

| Doc | Purpose |
|---|---|
| [Architecture report](./docs/architecture/PersonalAI-Architecture-Research.md) | The full research + high-level architecture (22 sections), incl. the roadmap. |
| [ADRs](./docs/architecture/adr/) | Architecture Decision Records. |
| [Threat model](./docs/architecture/THREAT-MODEL.md) | Trust boundaries and threats (v1). |
| [Security policy](./SECURITY.md) | Reporting and security posture. |
| [Dependency policy](./docs/policies/DEPENDENCY-POLICY.md) | Provenance, verification, SBOM, scanning rules. |
| [Supply-chain register](./docs/supply-chain/SUPPLY-CHAIN.md) | Living inventory of every dependency + creator. |
| [Onboarding / dev guide](./docs/ONBOARDING.md) | How to work in this repo. |
| [Releasing & versioning](./docs/development/releasing.md) | Version source of truth, release & signing. |
| [Contributing](./CONTRIBUTING.md) | GitHub flow, branching, commits, PRs. |
| [Changelog](./CHANGELOG.md) | Per-release history and the versioning policy. |

---

## Contributing & workflow

This repo uses **GitHub flow**: `main` is protected; all work happens on short-lived
feature branches merged via pull request. See [CONTRIBUTING.md](./CONTRIBUTING.md).

---

## License

[Apache-2.0](./LICENSE) © 2026 Lucian Hanga.
