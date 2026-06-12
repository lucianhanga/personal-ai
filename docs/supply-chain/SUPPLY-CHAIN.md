# Supply-Chain & Provenance Register

> **Living document.** This is the authoritative inventory of every third-party component
> PersonalAI depends on (or plans to adopt), with its **creator/maintainer, license, maturity,
> security considerations, reason for inclusion, and safer alternatives**.
>
> **Maintenance rule:** This file MUST be updated in the **same pull request** that adds,
> removes, upgrades, or changes the status of any dependency. See
> [Dependency Policy](../policies/DEPENDENCY-POLICY.md). A generated SBOM (CycloneDX) is the
> machine-readable companion to this human-readable register.

- **Last reviewed:** 2026-06-12 (security #275: patched the **esbuild** advisory (high — RCE via `NPM_CONFIG_REGISTRY`, missing binary integrity verification; affects `<0.28.1`, pulled transitively via `apps/ui` -> vite). Forced the patched line with a pnpm override `esbuild@<0.28.1 -> >=0.28.1` in `pnpm-workspace.yaml`, avoiding a disruptive vite 6->8 (rolldown) major bump. esbuild 0.28 declines to down-transform modern syntax to vite's old es2020 default, so the UI build target is pinned to `es2022` (a Tauri/modern-Chromium app; tsconfig already targets ES2022). Verified: `pnpm audit --audit-level high` clean, UI build + Vitest + Playwright green.)
- **Earlier:** 2026-06-12 (M8.1a: **langgraph-checkpoint** (MIT) promoted to a **direct** dependency of `personalai-storage-postgres` (`>=4.1,<5`) for the tenant-scoped LangGraph checkpointer `TenantCheckpointSaver` — it persists durable interrupt/resume state into RLS-isolated tables (migration 0014). Was already present transitively via LangGraph; now declared where used. No new transitive packages.)
- **Earlier:** 2026-06-12 (ADR-0012 / M8: **LangGraph** promoted `planned` -> `adopted` as the agent orchestration engine — see §2. Added as a `personalai-core` dependency `langgraph>=1.2,<2`. Transitive (LangChain ecosystem, all MIT): **langchain-core**, **langgraph-checkpoint**, **langgraph-prebuilt**, **langgraph-sdk**, plus **xxhash** (BSD). Usage surface kept tiny: LangGraph is the engine only; model+tool calls stay on our `ModelProvider`/`ToolGateway` seams, so the LangChain model/tool layers are not used.)
- **Earlier:** 2026-06-11 (IAM P1.2: added **argon2-cffi** for built-in password hashing — see the runtime table. Transitive: cffi/pycparser, already common.)
- **Earlier:** 2026-06-09 (M7: optional **MarkItDown-on-Ollama MCP** helper script `tools/markitdown-ollama/server.py` declares `markitdown[all]` + `openai` via PEP 723 inline metadata — **not** in the workspace lockfile; resolved into an ephemeral env only when the user runs it via `uv run --script`.)
- **Status legend:** `planned` (vetted, not yet in code) · `adopted` (in the build) · `evaluating` · `rejected`
- **Provenance note:** Licenses below are grounded in public sources cited in the architecture
  report. They MUST be re-verified against each project's `LICENSE` file at pin time (Phase 0).

---

## 1. Model runtimes & LLM serving

| Component | Maintainer / Org | License | Maturity | Status | Reason | Security notes | Alternatives |
|---|---|---|---|---|---|---|---|
| **Ollama** | Ollama | MIT (OSS) | Mature, very active | **adopted** (M1) | Default local runtime; `OllamaProvider` adapter via REST API | Loopback by default (egress guard allows loopback); validate all outputs | llama.cpp, vLLM, LM Studio API |
| **llama.cpp** | ggml-org / Georgi Gerganov | MIT | Mature (~109k★) | planned | Low-level inference, CPU/GGUF, max hardware reach | C/C++ surface; pin releases | Ollama (wraps it) |
| **vLLM** | vLLM project (OSS) | Apache-2.0 | Mature, active | planned | High-throughput GPU serving; guided decoding | Linux+GPU; server hardening | HF TGI |
| **LiteLLM** | BerriAI | MIT (Enterprise tier paid) | Mature, active | planned | Opt-in remote provider gateway + egress chokepoint | Handles provider API keys — keep in vault; egress logged | Direct provider SDKs |
| **Hugging Face (Transformers / TGI)** | Hugging Face | Apache-2.0 | Mature | evaluating | Source of weights/embeddings; alt serving | Verify model cards/weights provenance | Direct downloads |
| **LM Studio (OpenAI-compatible API)** | LM Studio | Proprietary app (OpenAI-compatible API) | Mature | evaluating | Desktop GUI users; optional endpoint only | App not open source — keep optional, never core | Ollama |
| **OpenAI-compatible APIs** (OpenAI/Azure/Together/Groq/OpenRouter/vLLM) | various | Service (per provider) | Mature | **adopted** (M2, via `personalai_provider_openai`) | Remote/frontier models via one adapter (httpx); opt-in | API key in secrets (never logged); egress allowlisted; off by default | LiteLLM (broader matrix, later) |

## 2. Backend, orchestration & schemas

| Component | Maintainer / Org | License | Maturity | Status | Reason | Security notes | Alternatives |
|---|---|---|---|---|---|---|---|
| **LangGraph** | LangChain | MIT (OSS) | Mature, active | **adopted** (M8, ADR-0012) | Agent orchestration engine: typed graph, checkpointing, human-in-the-loop interrupt/resume. Pinned `>=1.2,<2` in `personalai-core` | Ecosystem churn — pinned + used as engine only (model/tool calls stay on our seams, not LangChain's); transitive: langchain-core, langgraph-checkpoint/-prebuilt/-sdk, xxhash | Microsoft Agent Framework, PydanticAI |
| **Microsoft Agent Framework** | Microsoft | OSS (verify) | GA Q1 2026 | evaluating | Enterprise/.NET alt (AutoGen + Semantic Kernel successor) | Azure-leaning; verify license | LangGraph |
| **Pydantic** | Pydantic (Samuel Colvin et al.) | MIT | Mature | **adopted** (M0-3) | Python runtime validation; JSON-Schema bridge; strict fail-closed contracts | Pin major; `extra="forbid"` everywhere | attrs |
| **Zod** | Colin McDonnell | MIT | Mature | **adopted** (M0-3) | TS runtime validation; `.strict()` bindings shared with UI/extension | Pin major | io-ts, valibot |
| **JSON Schema** | JSON Schema Org / IETF | Spec (open) | Standard | **adopted** (M0-3) | Canonical interchange contract (generated from Pydantic into `schemas/json/`) | — | — |
| **FastAPI** | Sebastián Ramírez (tiangolo) | MIT | Mature, very active | **adopted** (M0-5) | Loopback API: async, typed, OpenAPI, Pydantic-native | Bind loopback; auth + origin allowlist; validate I/O | Litestar, Flask |
| **Uvicorn** | Encode | BSD-3-Clause | Mature | **adopted** (M0-5) | ASGI server for the backend | Bind loopback by default | Hypercorn |
| **Starlette** | Encode | BSD-3-Clause | Mature | **adopted** (M0-5, via FastAPI) | ASGI toolkit underlying FastAPI | — | — |
| **python-multipart** | Andrew Dunham / Encode | Apache-2.0 | Mature | **adopted** (M3-2) | Multipart file uploads for FastAPI | Size-limited uploads | — |
| **jsonschema** | Julian Berman | MIT | Very mature | **adopted** (M5-1) | Validate tool/MCP I/O against manifest JSON Schemas at the gateway | Core trust boundary for tool args/results | fastjsonschema |
| **argon2-cffi** | Hynek Schlawack | MIT | Very mature | **adopted** (IAM P1.2) | argon2id password hashing for the built-in IdentityProvider (ADR-0010) | The password trust boundary; OWASP/RFC 9106 recommended KDF; PHC strings only, never plaintext | bcrypt (weaker), scrypt |
| **mcp** (Python SDK) | Model Context Protocol (Anthropic) | MIT | Maturing | **adopted** (M7-1) | MCP client: connect to MCP servers (stdio/HTTP), list + call tools, wrapped behind the gateway | Third-party MCP servers are untrusted (manifest risk HIGH, sandboxed via executor tiers); the SDK itself only speaks the protocol | hand-rolled JSON-RPC client |
| **markitdown[all]** | Microsoft | MIT | Maturing | **opt-in tooling** (M7) | Document→Markdown conversion in the optional `tools/markitdown-ollama` MCP server | NOT in the workspace lockfile; runs as a separate stdio subprocess via `uv run --script`; parses untrusted files; HIGH-risk behind the gateway | official `markitdown-mcp` (no local LLM) |
| **openai** (SDK) | OpenAI | Apache-2.0 | Mature | **opt-in tooling** (M7) | OpenAI-compatible client used by the markitdown-ollama server to reach **Ollama** for image OCR | Same opt-in script; points at local Ollama (no remote calls); key is a dummy | httpx direct |
| **httpx** | Encode | BSD-3-Clause | Mature | **adopted** (M0-5 test; M1 runtime) | FastAPI TestClient transport; runtime HTTP client for the Ollama provider | — | — |

## 3. Storage & retrieval

| Component | Maintainer / Org | License | Maturity | Status | Reason | Security notes | Alternatives |
|---|---|---|---|---|---|---|---|
| **PostgreSQL** | PostgreSQL Global Dev Group | PostgreSQL License | Very mature | **adopted** (M3) | Relational + vector spine; `pgvector/pgvector` Docker image for dev/CI | Dev uses trust auth (no creds in code); prod via PERSONALAI_DATABASE_URL secret | SQLite (desktop single-user) |
| **pgvector** | pgvector (Andrew Kane) | PostgreSQL License | Mature (0.8.x) | **adopted** (M3) | Vectors in the same store (cosine/HNSW) | — | Qdrant |
| **asyncpg** | MagicStack | Apache-2.0 | Mature | **adopted** (M3) | Async Postgres driver for the storage adapters | Parameterized queries only | psycopg3 |
| **Qdrant** | Qdrant | Apache-2.0 | Mature | evaluating | Dedicated vector engine at scale (Rust) | Separate service to secure | Weaviate, Milvus, Chroma, LanceDB |
| **Apache AGE** | Apache Software Foundation | Apache-2.0 | Maturing | evaluating | Optional KAG/graph in Postgres (single-store) | — | Neo4j |
| **Neo4j** | Neo4j, Inc. | GPLv3 (Community) / commercial | Mature | evaluating | Dedicated graph store if KAG outgrows AGE | License (GPL) implications — review | Apache AGE |
| **MinIO** | MinIO, Inc. | AGPLv3 / commercial | Mature | evaluating | S3-compatible object store if needed | AGPL implications — review | Local encrypted FS |

## 4. Ingestion, OCR & audio

| Component | Maintainer / Org | License | Maturity | Status | Reason | Security notes | Alternatives |
|---|---|---|---|---|---|---|---|
| **Apache Tika** | Apache Software Foundation | Apache-2.0 | Very mature | planned | Broad file-type detection/parsing (~75 parsers) | Parse untrusted files in sandbox | Unstructured |
| **IBM Docling** | IBM Research (DS4SD) | Open source (verify, MIT-family) | Maturing, active | planned | AI layout + table extraction for complex PDFs | Runs AI models; sandbox; resource limits | Unstructured, Tika |
| **pypdf** | py-pdf | BSD-3-Clause | Mature | **adopted** (M3-2) | PDF text extraction (lightweight) | Parse untrusted files; text only | Docling, Tika |
| **python-docx** | python-openxml | MIT | Mature | **adopted** (M3-2) | DOCX text extraction | Text only | Docling, Tika |
| **faster-whisper** | SYSTRAN | MIT | Mature | planned | STT, ~4x faster than openai/whisper (CTranslate2) | Local; verify model weights | openai/whisper, WhisperLive |
| **OpenAI Whisper** | OpenAI | MIT | Mature | evaluating | Reference STT model/weights | — | faster-whisper |
| **Piper** | rhasspy | MIT | Mature | planned | Fast local neural TTS | Local | Coqui-family |
| **Tesseract OCR** | (UTC/Google-originated, community) | Apache-2.0 | Mature | evaluating | OCR fallback | — | Docling/Tika pipelines |

## 5. Client / desktop / extension

| Component | Maintainer / Org | License | Maturity | Status | Reason | Security notes | Alternatives |
|---|---|---|---|---|---|---|---|
| **Tauri** | Tauri Programme (Commons Conservancy) | MIT / Apache-2.0 | Mature (~70k★) | **adopted** (M0-6, scaffold) | Small, secure, capability-based desktop shell (ADR-0006) | Capability opt-in by default; built locally (no Rust in CI yet) | Electron |
| **Electron** | OpenJS Foundation | MIT | Very mature | evaluating | Fallback if WebView issues block delivery | Larger attack surface (Node in renderer) | Tauri |
| **React** | Meta | MIT | Very mature | **adopted** (M0-6) | SPA framework (ADR-0006) | Sanitize untrusted render; strict CSP | Svelte |
| **react-dom** | Meta | MIT | Very mature | adopted (M0-6) | React DOM renderer | — | — |
| **react-markdown** | unified / remark collective (Titus Wormer) | MIT | Mature | adopted (UX) | Render assistant replies as Markdown | No raw HTML (no rehype-raw); default urlTransform strips `javascript:` | markdown-it + sanitizer |
| **remark-gfm** | unified / remark collective | MIT | Mature | adopted (UX) | GFM (tables, task lists, strikethrough) for react-markdown | — | — |
| **Svelte** | Svelte (Rich Harris et al.) | MIT | Mature | rejected | Considered for the SPA; React chosen (ADR-0006) | — | React |
| **@vitejs/plugin-react** | Vite team (VoidZero) | MIT | Mature | adopted (M0-6) | React support for Vite | — | — |

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
| **Sigstore / cosign** | OpenSSF / Linux Foundation | Apache-2.0 | Mature | **adopted** (M0-9) | Keyless release signing + CI signing smoke | Keyless via GitHub OIDC; verify on consume | GPG signing |
| **cosign-installer (action)** | sigstore | Apache-2.0 | Mature | adopted (M0-9) | Installs cosign in CI | Pinned to major `@v3` | manual install |

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
| **Vitest** | Vitest team (VoidZero) | MIT | Mature | adopted (M0-3, `>=4.1.0`) | TS unit tests | Pinned `>=4.1.0` to clear GHSA-5xrq-8626-4rwp (UI-server RCE) | Jest |
| **Vite** | Vite team (VoidZero) | MIT | Mature | adopted (M0-8, via Vitest 4) | Build/test toolchain for Vitest 4 | — | — |
| **esbuild** | Evan Wallace | MIT | Mature | adopted (M0-3, transitive via Vite/Vitest) | TS transform for tests | Build script approved in pnpm-workspace.yaml | — |
| **pip-audit** | PyPA | Apache-2.0 | Mature | adopted (M0-8) | Python vulnerability scanning in CI | Queries PyPI advisory DB | Trivy, Grype |
| **cyclonedx-bom** | CycloneDX (OWASP) | Apache-2.0 | Mature | adopted (M0-8) | Generates the CycloneDX SBOM | — | Syft |
| **detect-secrets** | Yelp | Apache-2.0 | Mature | adopted (M0-10) | Secret scanning (pre-commit + CI) with a committed baseline | Baseline reviewed on change | gitleaks, trufflehog |
| **pre-commit** | pre-commit (Anthony Sottile) | MIT | Mature | adopted (M0-10) | Local git hooks (secret scan, ruff) | Hooks call pinned uv tools | — |
| **fpdf2** | PyFPDF / Lucas Cimon | LGPL-3.0 (lib) | Mature | adopted (M3-2, dev) | Generate sample PDFs in tests | Test-only; not shipped | reportlab |
| **types-jsonschema** | python/typeshed | Apache-2.0 | Mature | adopted (M5-1, dev) | Type stubs for jsonschema | Test/type-only | — |
| **Playwright** | Microsoft | Apache-2.0 | Mature | adopted (M0-6) | UI e2e (Chromium) | Browsers pinned via lockfile; installed in CI | Cypress |
| **Testing Library (react, jest-dom)** | Testing Library (Kent C. Dodds et al.) | MIT | Mature | adopted (M0-6) | React component tests | — | — |
| **jsdom** | jsdom | MIT | Mature | adopted (M0-6) | DOM env for Vitest | — | happy-dom |
| **respx** | Jonas Lundberg | BSD-3-Clause | Mature | adopted (M1) | Mock httpx in tests (Ollama provider) | — | pytest-httpx |

---

## 8. How this register is kept up to date

1. Any PR that touches dependencies updates this file **and** the generated SBOM in the same change.
2. CI fails if a manifest changes but this register / SBOM does not (drift check — added at M0/M7).
3. Each entry must keep: maintainer, license, maturity, status, reason, security notes, alternatives.
4. License claims are re-verified from upstream `LICENSE` at pin time; uncertain ones are marked `(verify)`.
5. Quarterly review of `evaluating` entries to promote, keep, or `reject` them.
