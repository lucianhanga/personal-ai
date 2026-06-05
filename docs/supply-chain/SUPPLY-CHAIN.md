# Supply-Chain & Provenance Register

> **Living document.** This is the authoritative inventory of every third-party component
> PersonalAI depends on (or plans to adopt), with its **creator/maintainer, license, maturity,
> security considerations, reason for inclusion, and safer alternatives**.
>
> **Maintenance rule:** This file MUST be updated in the **same pull request** that adds,
> removes, upgrades, or changes the status of any dependency. See
> [Dependency Policy](../policies/DEPENDENCY-POLICY.md). A generated SBOM (CycloneDX) is the
> machine-readable companion to this human-readable register.

- **Last reviewed:** 2026-06-05 (M0-3: pydantic adopted; zod/typescript/vitest added)
- **Status legend:** `planned` (vetted, not yet in code) · `adopted` (in the build) · `evaluating` · `rejected`
- **Provenance note:** Licenses below are grounded in public sources cited in the architecture
  report. They MUST be re-verified against each project's `LICENSE` file at pin time (Phase 0).

---

## 1. Model runtimes & LLM serving

| Component | Maintainer / Org | License | Maturity | Status | Reason | Security notes | Alternatives |
|---|---|---|---|---|---|---|---|
| **Ollama** | Ollama | MIT (OSS) | Mature, very active | planned | Default local runtime; easy model mgmt; native JSON-Schema structured outputs + tool calling | Runs models locally; keep bound to loopback; validate all outputs | llama.cpp, vLLM, LM Studio API |
| **llama.cpp** | ggml-org / Georgi Gerganov | MIT | Mature (~109k★) | planned | Low-level inference, CPU/GGUF, max hardware reach | C/C++ surface; pin releases | Ollama (wraps it) |
| **vLLM** | vLLM project (OSS) | Apache-2.0 | Mature, active | planned | High-throughput GPU serving; guided decoding | Linux+GPU; server hardening | HF TGI |
| **LiteLLM** | BerriAI | MIT (Enterprise tier paid) | Mature, active | planned | Opt-in remote provider gateway + egress chokepoint | Handles provider API keys — keep in vault; egress logged | Direct provider SDKs |
| **Hugging Face (Transformers / TGI)** | Hugging Face | Apache-2.0 | Mature | evaluating | Source of weights/embeddings; alt serving | Verify model cards/weights provenance | Direct downloads |
| **LM Studio (OpenAI-compatible API)** | LM Studio | Proprietary app (OpenAI-compatible API) | Mature | evaluating | Desktop GUI users; optional endpoint only | App not open source — keep optional, never core | Ollama |

## 2. Backend, orchestration & schemas

| Component | Maintainer / Org | License | Maturity | Status | Reason | Security notes | Alternatives |
|---|---|---|---|---|---|---|---|
| **LangGraph** | LangChain | MIT (OSS) | Mature, active | planned | Graph orchestration, checkpointing, human-in-the-loop | Ecosystem churn — pin versions | Microsoft Agent Framework |
| **Microsoft Agent Framework** | Microsoft | OSS (verify) | GA Q1 2026 | evaluating | Enterprise/.NET alt (AutoGen + Semantic Kernel successor) | Azure-leaning; verify license | LangGraph |
| **Pydantic** | Pydantic (Samuel Colvin et al.) | MIT | Mature | **adopted** (M0-3) | Python runtime validation; JSON-Schema bridge; strict fail-closed contracts | Pin major; `extra="forbid"` everywhere | attrs |
| **Zod** | Colin McDonnell | MIT | Mature | **adopted** (M0-3) | TS runtime validation; `.strict()` bindings shared with UI/extension | Pin major | io-ts, valibot |
| **JSON Schema** | JSON Schema Org / IETF | Spec (open) | Standard | **adopted** (M0-3) | Canonical interchange contract (generated from Pydantic into `schemas/json/`) | — | — |
| **FastAPI** | Sebastián Ramírez (tiangolo) | MIT | Mature, very active | **adopted** (M0-5) | Loopback API: async, typed, OpenAPI, Pydantic-native | Bind loopback; auth + origin allowlist; validate I/O | Litestar, Flask |
| **Uvicorn** | Encode | BSD-3-Clause | Mature | **adopted** (M0-5) | ASGI server for the backend | Bind loopback by default | Hypercorn |
| **Starlette** | Encode | BSD-3-Clause | Mature | **adopted** (M0-5, via FastAPI) | ASGI toolkit underlying FastAPI | — | — |
| **httpx** | Encode | BSD-3-Clause | Mature | **adopted** (M0-5, dev/test) | Test client transport for FastAPI TestClient | — | — |

## 3. Storage & retrieval

| Component | Maintainer / Org | License | Maturity | Status | Reason | Security notes | Alternatives |
|---|---|---|---|---|---|---|---|
| **PostgreSQL** | PostgreSQL Global Dev Group | PostgreSQL License | Very mature | planned | Relational + metadata + conversation history spine | Standard DB hardening; encryption at rest | SQLite (desktop single-user) |
| **pgvector** | pgvector (Andrew Kane) | PostgreSQL License | Mature | planned | Vectors in the same store as relational data | — | Qdrant |
| **Qdrant** | Qdrant | Apache-2.0 | Mature | evaluating | Dedicated vector engine at scale (Rust) | Separate service to secure | Weaviate, Milvus, Chroma, LanceDB |
| **Apache AGE** | Apache Software Foundation | Apache-2.0 | Maturing | evaluating | Optional KAG/graph in Postgres (single-store) | — | Neo4j |
| **Neo4j** | Neo4j, Inc. | GPLv3 (Community) / commercial | Mature | evaluating | Dedicated graph store if KAG outgrows AGE | License (GPL) implications — review | Apache AGE |
| **MinIO** | MinIO, Inc. | AGPLv3 / commercial | Mature | evaluating | S3-compatible object store if needed | AGPL implications — review | Local encrypted FS |

## 4. Ingestion, OCR & audio

| Component | Maintainer / Org | License | Maturity | Status | Reason | Security notes | Alternatives |
|---|---|---|---|---|---|---|---|
| **Apache Tika** | Apache Software Foundation | Apache-2.0 | Very mature | planned | Broad file-type detection/parsing (~75 parsers) | Parse untrusted files in sandbox | Unstructured |
| **IBM Docling** | IBM Research (DS4SD) | Open source (verify, MIT-family) | Maturing, active | planned | AI layout + table extraction for complex PDFs | Runs AI models; sandbox; resource limits | Unstructured, Tika |
| **faster-whisper** | SYSTRAN | MIT | Mature | planned | STT, ~4x faster than openai/whisper (CTranslate2) | Local; verify model weights | openai/whisper, WhisperLive |
| **OpenAI Whisper** | OpenAI | MIT | Mature | evaluating | Reference STT model/weights | — | faster-whisper |
| **Piper** | rhasspy | MIT | Mature | planned | Fast local neural TTS | Local | Coqui-family |
| **Tesseract OCR** | (UTC/Google-originated, community) | Apache-2.0 | Mature | evaluating | OCR fallback | — | Docling/Tika pipelines |

## 5. Client / desktop / extension

| Component | Maintainer / Org | License | Maturity | Status | Reason | Security notes | Alternatives |
|---|---|---|---|---|---|---|---|
| **Tauri** | Tauri Programme (Commons Conservancy) | MIT / Apache-2.0 | Mature (~70k★) | planned | Small, secure, capability-based desktop shell | Capability opt-in by default | Electron |
| **Electron** | OpenJS Foundation | MIT | Very mature | evaluating | Fallback if WebView issues block delivery | Larger attack surface (Node in renderer) | Tauri |
| **React** | Meta | MIT | Very mature | evaluating | SPA option | Sanitize untrusted render | Svelte |
| **Svelte** | Svelte (Rich Harris et al.) | MIT | Mature | evaluating | SPA option (lean) | Sanitize untrusted render | React |

## 6. Tooling: protocol, sandbox, security, observability

| Component | Maintainer / Org | License | Maturity | Status | Reason | Security notes | Alternatives |
|---|---|---|---|---|---|---|---|
| **Model Context Protocol (MCP)** | Anthropic + community | Open standard (MIT SDKs) | Maturing, active | planned | Tool/MCP interop standard | Spec does NOT enforce security — implementor's job; CVE history (e.g. CVE-2025-6514) | Bespoke tool API |
| **gVisor** | Google | Apache-2.0 | Mature | evaluating | Syscall-isolation sandbox tier | Linux-centric | Firecracker, containers |
| **Firecracker** | AWS | Apache-2.0 | Mature | evaluating | microVM isolation for untrusted code | Linux/KVM | Kata, gVisor |
| **Wasmtime** | Bytecode Alliance | Apache-2.0 | Mature | evaluating | WASM capability-sandboxed plugins | Capability-deny by default | WasmEdge |
| **OpenTelemetry** | CNCF | Apache-2.0 | Mature | planned | Traces/metrics/logs | — | Vendor APMs |
| **Langfuse** | Langfuse | MIT (OSS core) | Maturing | evaluating | Local agent-trace observability | Self-host | OTel only |
| **CycloneDX / SPDX** | OWASP / Linux Foundation | Apache-2.0 / CC | Standard | planned | SBOM formats | — | — |
| **Trivy** | Aqua Security | Apache-2.0 | Mature | planned | Vulnerability & SBOM scanning | — | Grype |
| **Grype** | Anchore | Apache-2.0 | Mature | evaluating | Vulnerability scanning | — | Trivy |
| **Sigstore / cosign** | OpenSSF / Linux Foundation | Apache-2.0 | Mature | planned | Release signing | — | GPG signing |

## 7. Build & development tooling (adopted)

Dev/build/test toolchain in use from M0-1/M0-3. Not shipped to end users but part of the
supply chain (build integrity).

| Component | Maintainer / Org | License | Maturity | Status | Reason | Security notes | Alternatives |
|---|---|---|---|---|---|---|---|
| **uv** | Astral | Apache-2.0 / MIT | Mature, very active | adopted (M0-1) | Python workspace + reproducible installs | Lockfile committed | Poetry, pip-tools |
| **Ruff** | Astral | MIT | Mature | adopted (M0-1) | Lint + format | — | flake8/black/isort |
| **mypy** | Python / mypy team | MIT | Mature | adopted (M0-1) | Strict static typing | — | pyright |
| **pytest / pytest-cov** | pytest-dev | MIT | Mature | adopted (M0-1) | Tests + coverage gate | — | unittest |
| **import-linter** | David Seddon | BSD-2-Clause | Mature | adopted (M0-1) | Enforces hexagonal dependency direction | — | custom checks |
| **hatchling** | PyPA (Hatch) | MIT | Mature | adopted (M0-1) | Build backend | — | setuptools, flit |
| **pnpm** | pnpm (OpenJS-adjacent) | MIT | Mature | adopted (M0-1) | JS workspaces, strict isolation | Lockfile committed; approve build scripts explicitly | npm, yarn |
| **TypeScript** | Microsoft | Apache-2.0 | Very mature | adopted (M0-3) | Typed TS contracts/UI | — | — |
| **Vitest** | Vitest team (VoidZero) | MIT | Mature | adopted (M0-3) | TS unit tests | — | Jest |
| **esbuild** | Evan Wallace | MIT | Mature | adopted (M0-3, transitive via Vitest) | TS transform for tests | Build script approved in pnpm-workspace.yaml | — |

---

## 8. How this register is kept up to date

1. Any PR that touches dependencies updates this file **and** the generated SBOM in the same change.
2. CI fails if a manifest changes but this register / SBOM does not (drift check — added at M0/M7).
3. Each entry must keep: maintainer, license, maturity, status, reason, security notes, alternatives.
4. License claims are re-verified from upstream `LICENSE` at pin time; uncertain ones are marked `(verify)`.
5. Quarterly review of `evaluating` entries to promote, keep, or `reject` them.
