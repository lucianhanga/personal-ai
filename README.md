# PersonalAI

[![CI](https://github.com/lucianhanga/personal-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/lucianhanga/personal-ai/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Status: M6 — agent](https://img.shields.io/badge/status-M6%20%E2%80%94%20agent%20loop-brightgreen.svg)](./docs/guides/agent.md)
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

> **Current state (v0.6.0):** **M0–M6 complete** — streaming chat in a React UI over **local Ollama
> models** or **remote OpenAI-compatible providers**, **chat-with-your-documents** (file ingestion →
> pgvector RAG with citations), **persistent conversation history**, **memory** (per-chat short-term
> summary + cross-chat long-term memory you can view/edit/erase), a security-first **Tool gateway**
> (permissions, egress allowlist, schema-validated I/O, risk approval, audit), and a **single-agent
> loop** that autonomously calls tools (calculator, web search) and **streams reasoning + answer**
> token-by-token. The HTTP API is versioned under **`/api/v1`** (see [CHANGELOG](./CHANGELOG.md)).
> See the
> [architecture report](./docs/architecture/PersonalAI-Architecture-Research.md), the
> [local chat guide](./docs/guides/local-chat.md), [remote providers](./docs/guides/remote-providers.md),
> [files + RAG](./docs/guides/files-and-rag.md), [memory](./docs/guides/memory.md),
> [tools](./docs/guides/tools.md), and [the agent loop](./docs/guides/agent.md).

## Quickstart (local chat)

```bash
make setup
# terminal 1 — backend
PERSONALAI_AUTH_TOKEN=demo PERSONALAI_DEFAULT_MODEL=qwen3.6:35b-a3b make run-backend
# terminal 2 — UI -> http://localhost:5173 (token: demo)
pnpm --filter @personalai/ui dev
```

Requires a local [Ollama](https://ollama.com) with a model pulled. Full guide:
[docs/guides/local-chat.md](./docs/guides/local-chat.md).

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

## High-level architecture

A **single-host modular monolith** (hexagonal: ports & adapters + registries) fronting isolated
runtimes — local model servers and **sandboxed** tools/MCP servers — with security, audit, and
secrets as cross-cutting layers.

```
Clients (Tauri UI + MV3 extension, loopback)
        │
   API Gateway ── Auth/Settings
        │
   Conversation ── Agent Orchestration (M6: hand-rolled loop; LangGraph at M8) ── Structured-Output Validation
        │                    │
   File Ingestion       Tool/MCP Gateway ── Security Engine ── Sandbox (container/gVisor/WASM)
        │                    │
   Retrieval (RAG)      Model Abstraction/Router ── Ollama | llama.cpp | vLLM | remote (LiteLLM, opt-in)
        │
   Storage: PostgreSQL + pgvector · object store · secrets vault · append-only audit
```

Full diagram and rationale: [architecture report](./docs/architecture/PersonalAI-Architecture-Research.md).

---

## Selected stack (planned, vetted)

| Area | Choice | License |
|---|---|---|
| Backend | Python + FastAPI (modular monolith) | — |
| UI | Tauri shell + web SPA (React/Svelte) | MIT/Apache-2.0 |
| Local model runtime | Ollama (default) · llama.cpp · vLLM | MIT / MIT / Apache-2.0 |
| Remote provider gateway | LiteLLM (opt-in) | MIT |
| Agent orchestration | LangGraph | MIT |
| Schemas | Pydantic / Zod + JSON Schema | MIT |
| Storage / RAG | PostgreSQL + pgvector | PostgreSQL License |
| Ingestion | Apache Tika / IBM Docling | Apache-2.0 |
| Audio | faster-whisper (STT) / Piper (TTS) | MIT |

The **complete, maintained** provenance register (maintainer, license, maturity, security notes,
reason, alternatives) lives in
[`docs/supply-chain/SUPPLY-CHAIN.md`](./docs/supply-chain/SUPPLY-CHAIN.md).

---

## Roadmap (high horizon)

`Foundation → Talk → Know → Act → Reason → Sense → Reach → (Connect) → Harden`

| Milestone | Delivers | Status |
|---|---|---|
| **M0** | Skeleton + contracts (all ports defined, CI/SBOM/signing skeleton) | done |
| **M1–M2** | Local chat (Ollama) → provider portability | done |
| **M3** | Files + vector RAG (pgvector) | done |
| **M4** | Memory (short-term summary + long-term, semantic) | done |
| **M5** | Tool/MCP gateway + sandbox | done |
| **M6** | Single-agent loop + tools (streamed reasoning + answer) | done |
| **M7** | MCP plug-in/out + verification (next) | planned |
| **M8** | Multi-agent + selective verification | planned |
| **M9** | Multimodal (vision / STT / TTS) | planned |
| **M10** | Browser extension (MV3) | planned |
| **M11** | KAG / graph memory (graph upgrade of M4) | planned |
| **M12** | Hardening, signing, packaging, docs | planned |

Details: [§22 Modular Implementation Roadmap](./docs/architecture/PersonalAI-Architecture-Research.md#22-modular-implementation-roadmap).

---

## Documentation

| Doc | Purpose |
|---|---|
| [Architecture report](./docs/architecture/PersonalAI-Architecture-Research.md) | The full research + high-level architecture (22 sections). |
| [ADRs](./docs/architecture/adr/) | Architecture Decision Records. |
| [Threat model](./docs/architecture/THREAT-MODEL.md) | Trust boundaries and threats (v1). |
| [Security policy](./SECURITY.md) | Reporting and security posture. |
| [Dependency policy](./docs/policies/DEPENDENCY-POLICY.md) | Provenance, verification, SBOM, scanning rules. |
| [Supply-chain register](./docs/supply-chain/SUPPLY-CHAIN.md) | Living inventory of every dependency + creator. |
| [Onboarding / dev guide](./docs/ONBOARDING.md) | How to work in this repo. |
| [Contributing](./CONTRIBUTING.md) | GitHub flow, branching, commits, PRs. |
| [Changelog](./CHANGELOG.md) | Versioning policy (semver in `VERSION`) and per-release history. |

---

## Contributing & workflow

This repo uses **GitHub flow**: `main` is protected; all work happens on short-lived
feature branches merged via pull request. See [CONTRIBUTING.md](./CONTRIBUTING.md).

---

## License

[Apache-2.0](./LICENSE) © 2026 Lucian Hanga.
