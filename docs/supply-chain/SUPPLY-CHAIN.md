# Supply-Chain & Provenance Register

> **What this is.** The authoritative inventory of every third-party component PersonalAI
> **actually depends on today** — what is declared in a manifest/lockfile or wired into CI.
> For each component it records the maintainer, license, and what it is used for.
>
> **Scope rule:** this register lists **adopted** components only. Roads not taken
> (evaluated, planned, or rejected alternatives) are out of scope and live in ADRs or the
> architecture research, not here.
>
> **Maintenance rule:** this file MUST be updated in the **same pull request** that adds,
> removes, or upgrades any dependency. CI enforces this with a drift check (see the end of
> this file and the [Dependency Policy](../policies/DEPENDENCY-POLICY.md)). The generated
> CycloneDX SBOM (`sbom/python.cdx.json`) is the machine-readable companion to this register.

- **Last reviewed:** 2026-06-30 (added `mermaid`, `dompurify`, `@types/dompurify` for chat diagram/image rendering; `httpx` now a direct `personalai-core` dep + capped `<0.29` for the SSRF image-localize floor, #517).

---

## How the stack is built

| Aspect | Toolchain |
|---|---|
| Python | 3.12; package/workspace manager **uv** (`uv.lock` committed); build backend **hatchling** |
| JS/TS | Node >= 20 (CI runs Node 22); package manager **pnpm@11.5.1** (`pnpm-lock.yaml` committed) |
| Desktop shell | **Tauri 2** (Rust). See the reproducibility gap note in section 5 |

The Python side is a uv workspace of modular packages (`contracts`, `core`, `apps/backend`,
`providers/*`, `storage/postgres`, `modalities/files`, `tools/*`). The JS side is a pnpm
workspace (`apps/ui`, `packages/contracts`).

---

## 1. Model runtimes & LLM serving

| Component | Maintainer | License | Used for |
|---|---|---|---|
| **Ollama** | Ollama | MIT | Default local model runtime; reached over its REST API by `personalai_provider_ollama` (via `httpx`). Loopback by default; the egress guard allows loopback. |
| **OpenAI-compatible APIs** | various providers | Service (per provider) | Optional remote/frontier models through one adapter (`personalai_provider_openai`, via `httpx`). Opt-in, off by default; API keys kept in secrets and never logged; egress allowlisted. |

## 2. Backend, orchestration & schemas

| Component | Maintainer | License | Used for |
|---|---|---|---|
| **LangGraph** (`langgraph>=1.2,<2`) | LangChain | MIT | Agent orchestration engine (typed graph, checkpointing, human-in-the-loop interrupt/resume) in `personalai-core`. Used as the engine only; model/tool calls stay on our own `ModelProvider`/`ToolGateway` seams. |
| **langchain-core** (`>=1.4,<2`) | LangChain | MIT | RAG retriever/embeddings adapter interfaces (`BaseRetriever`, `Embeddings`, `Document`) in `personalai-backend`. Direct pin (resolved 1.4.6) so a downgrade below the CVE-2025-68664 fix is blocked. We never call LangChain `load()/loads()` on untrusted data; `langsmith` tracing is force-disabled at startup. |
| **langgraph-checkpoint** (`>=4.1,<5`) | LangChain | MIT | LangGraph checkpointer backend (`TenantCheckpointSaver`) in `personalai-storage-postgres`; persists interrupt/resume state into RLS-isolated tables. |
| **Pydantic** (`>=2.7`) | Pydantic (Samuel Colvin et al.) | MIT | Python runtime validation and the JSON-Schema bridge in `personalai-contracts`; strict, fail-closed contracts (`extra="forbid"`). |
| **jsonschema** (`>=4.21`) | Julian Berman | MIT | Validates tool/MCP I/O against manifest JSON Schemas at the gateway in `personalai-core`. |
| **FastAPI** (`>=0.111`) | Sebastián Ramírez (tiangolo) | MIT | The loopback HTTP API in `personalai-backend` (async, typed, OpenAPI, Pydantic-native). Pulls in Starlette (Encode, BSD-3-Clause). |
| **Uvicorn** (`>=0.30`) | Encode | BSD-3-Clause | ASGI server for the backend; binds loopback by default. |
| **python-multipart** (`>=0.0.9`) | Andrew Dunham / Encode | Apache-2.0 | Multipart file uploads for FastAPI. |
| **argon2-cffi** (`>=23.1`) | Hynek Schlawack | MIT | argon2id password hashing for the built-in identity provider (ADR-0010). PHC strings only, never plaintext. |
| **python-dotenv** (`>=1.0`) | theskumar (Saurabh Kumar) | BSD-3-Clause | Loads `PERSONALAI_*` from a local `.env` at backend startup. `load_dotenv()` does not override the real environment, so prod/CI are unaffected. |
| **watchdog** (`>=4.0`) | gorakhargosh | Apache-2.0 | Cross-platform filesystem watcher (FSEvents/inotify/ReadDirectoryChangesW + polling fallback) for Settings -> Documents folder sync in `personalai-backend`. Observes user-allowlisted roots only; the sync worker is local-provider-only and fail-closed (no egress). |
| **mcp** (Python SDK) (`>=1.0`) | Model Context Protocol (Anthropic) | MIT | MCP client in `personalai-tool-mcp`: connect to MCP servers (stdio/HTTP), list and call tools, wrapped behind the gateway. Third-party MCP servers themselves are treated as untrusted. |
| **httpx** (`>=0.27,<0.29`) | Encode | BSD-3-Clause | Runtime HTTP client shared by `providers/ollama`, `providers/openai_compat`, `tools/builtin`, and now `personalai-core` directly (the SSRF floor `security/ssrf.py` that backs the image-localize endpoint); also the FastAPI TestClient transport. Capped `<0.29` because the SSRF floor pins TLS via httpcore's `sni_hostname` request extension — a deliberate bump + security re-review is required before crossing it (#517). |

## 3. Storage & retrieval

| Component | Maintainer | License | Used for |
|---|---|---|---|
| **PostgreSQL** | PostgreSQL Global Dev Group | PostgreSQL License | Relational + vector spine. Dev/CI use the `pgvector/pgvector` Docker image; prod connects via the `PERSONALAI_DATABASE_URL` secret. (Service dependency, not a Python package.) |
| **pgvector** | Andrew Kane | PostgreSQL License | Vector storage/search (cosine/HNSW) inside the same Postgres store. Ships in the dev/CI Docker image. |
| **asyncpg** (`>=0.29`) | MagicStack | Apache-2.0 | Async Postgres driver behind the storage adapters in `personalai-storage-postgres`. Parameterized queries only. |
| **transformers** (`>=4.51`, optional) | Hugging Face | Apache-2.0 | Cross-encoder reranker in `personalai-provider-hf-reranker` (`RERANK_MODEL`, default `Qwen/Qwen3-Reranker-0.6B`). **Optional, flag-gated** (`RERANK_ENABLED`, off by default); installed only via the package's `ml` extra, so the heavy ML stack has no footprint unless reranking is enabled. Weights fetched once from Hugging Face, then run locally. |
| **torch** (`>=2.4`, optional) | PyTorch Foundation (Linux Foundation) | BSD-3-Clause | Inference backend for the optional cross-encoder reranker (`ml` extra of `personalai-provider-hf-reranker`). Same flag gate (`RERANK_ENABLED`, off by default); not installed in the default footprint. |

## 4. Ingestion, OCR & audio

| Component | Maintainer | License | Used for |
|---|---|---|---|
| **pypdf** (`>=4.0`) | py-pdf | BSD-3-Clause | Lightweight PDF text extraction in `personalai-modality-files`. |
| **python-docx** (`>=1.1`) | python-openxml | MIT | DOCX text extraction in `personalai-modality-files`. |
| **rapidocr-onnxruntime** (`>=1.2`) | RapidAI | Apache-2.0 | OCR fallback for scanned / image-only PDFs (PaddleOCR models via ONNX Runtime). Runs fully on-device; models ship in the wheel, no egress or key. |
| **pypdfium2** (`>=4.0`) | pypdfium2-team (PDFium by Google) | Apache-2.0 / BSD-3-Clause | Rasterizes PDF pages to images to feed RapidOCR. Permissive PDFium binding (the AGPL PyMuPDF alternative was avoided). |
| **faster-whisper** (`>=1.1`) | SYSTRAN | MIT | In-process local speech-to-text (CTranslate2) in `personalai-provider-whisper-local`; default transcribe provider, multilingual. Weights fetched once from Hugging Face, then run offline. |

## 5. Client / desktop

| Component | Maintainer | License | Used for |
|---|---|---|---|
| **Tauri 2** | Tauri Programme (Commons Conservancy) | MIT / Apache-2.0 | Capability-based desktop shell (`apps/ui/src-tauri`, ADR-0006) wrapping the React SPA. |
| **React** (`^19`) | Meta | MIT | UI framework for the SPA in `apps/ui`. |
| **react-dom** (`^19`) | Meta | MIT | React DOM renderer. |
| **react-markdown** (`^9`) | unified / remark collective | MIT | Renders assistant replies as Markdown. No raw HTML (no rehype-raw); default URL transform strips `javascript:`. |
| **remark-gfm** (`^4`) | unified / remark collective | MIT | GFM tables, task lists, and strikethrough for react-markdown. |
| **mermaid** (`^11.10.0`) | Mermaid (Knut Sveidqvist et al.) | MIT | Renders ```mermaid fenced code blocks in chat as diagrams. Lazy-loaded (its own Vite chunk; zero initial-load cost). Pinned `>=11.10.0` (CVE-2025-54880/54881 render-time XSS sinks fixed in 11.10.0); rendered with `securityLevel: 'strict'` and the SVG output sanitized via DOMPurify before injection. |
| **dompurify** (`^3`) | Cure53 | Apache-2.0 / MPL-2.0 | Sanitizes the SVG produced by mermaid (strict SVG profile; forbids `foreignObject`/`script`/`iframe`/`a` and event-handler attributes) before it is injected into the DOM via `dangerouslySetInnerHTML`. |
| **react-force-graph-2d** (`^1.29`) | Vasco Asturiano | MIT | 2D force-directed graph visualization in the UI (knowledge/graph view). |
| **gpt-tokenizer** (`^3.4`) | dqbd | MIT | Pure-JS, in-browser BPE tokenizer (o200k_base) used UI-only to render an approximate token visualization of the assembled-context panel. No network, no weights. |
| **zod** (`^3.23`) | Colin McDonnell | MIT | TS runtime validation in `packages/contracts`, aligned with the Python/JSON-Schema contracts. |

> **Tauri 2 reproducibility gap:** the Rust shell (`apps/ui/src-tauri/Cargo.toml`) declares
> `tauri`/`tauri-build` at major version `2`, but **no `Cargo.lock` is committed**, so the
> Rust dependency graph is not pinned and the desktop build is not byte-reproducible. The
> Tauri/Rust build is also not run in CI (see section 7). Pinning a `Cargo.lock` is the fix.

## 6. Release signing

| Component | Maintainer | License | Used for |
|---|---|---|---|
| **Sigstore / cosign** | OpenSSF / Linux Foundation | Apache-2.0 | Signing the release artifacts and SBOM (keyless via GitHub OIDC in `release.yml`), plus an offline signing smoke test in CI. |
| **cosign-installer** (action) | sigstore | Apache-2.0 | Installs cosign in CI; pinned to major `@v3`. |

## 7. Build, test & supply-chain tooling (dev group)

Declared in the root `pyproject.toml` `dev` group (Python) and `apps/ui` / `packages/contracts`
devDependencies (JS). Not shipped to end users, but part of build integrity.

**Python (uv `dev` group):**

| Component | Maintainer | License | Used for |
|---|---|---|---|
| **uv** | Astral | Apache-2.0 / MIT | Python workspace resolver + installer; `uv.lock` committed. |
| **Ruff** (`>=0.6`) | Astral | MIT | Lint + format (replaces black/isort/flake8). |
| **mypy** (`>=1.11`) | mypy team | MIT | Strict static typing. |
| **pytest / pytest-cov** (`>=8.2` / `>=5.0`) | pytest-dev | MIT | Tests + coverage gate. |
| **import-linter** (`>=2.0`) | David Seddon | BSD-2-Clause | Enforces the hexagonal dependency direction. |
| **hatchling** | PyPA (Hatch) | MIT | Build backend for the Python packages. |
| **pip-audit** (`>=2.7`) | PyPA | Apache-2.0 | Python vulnerability scanning in CI (PyPI advisory DB). |
| **cyclonedx-bom** (`>=4.0`) | CycloneDX (OWASP) | Apache-2.0 | Generates the CycloneDX SBOM (`cyclonedx-py requirements`). |
| **detect-secrets** (`>=1.5`) | Yelp | Apache-2.0 | Secret scanning (pre-commit + CI) against a committed baseline. |
| **pre-commit** (`>=3.7`) | Anthony Sottile | MIT | Local git hooks (secret scan, ruff). |
| **respx** (`>=0.21`) | Jonas Lundberg | BSD-3-Clause | Mocks httpx in tests. |
| **fpdf2** (`>=2.7`) | Lucas Cimon (PyFPDF) | LGPL-3.0 | Generates sample PDFs in tests (test-only, not shipped). |
| **types-jsonschema** (`>=4.21`) | python/typeshed | Apache-2.0 | Type stubs for jsonschema (type-only). |

**JS/TS (pnpm devDependencies):**

| Component | Maintainer | License | Used for |
|---|---|---|---|
| **TypeScript** (`^5.5`) | Microsoft | Apache-2.0 | Typed TS for the UI and contracts. |
| **Vite** (`^6`) | VoidZero / Vite team | MIT | Build + dev server for the UI; test runner backend for Vitest. |
| **Vitest** (`^4`) | VoidZero / Vitest team | MIT | TS unit tests. |
| **@vitejs/plugin-react** (`^5`) | VoidZero / Vite team | MIT | React support for Vite. |
| **@playwright/test** (`^1.48`) | Microsoft | Apache-2.0 | UI end-to-end tests (Chromium). |
| **@testing-library/react, @testing-library/jest-dom** | Testing Library | MIT | React component tests. |
| **jsdom** (`^25`) | jsdom | MIT | DOM environment for Vitest. |
| **@types/react, @types/react-dom** (`^19`) | DefinitelyTyped | MIT | React type definitions (type-only). |
| **@types/dompurify** (`^3`) | DefinitelyTyped | MIT | DOMPurify type definitions (type-only, dev). |

**pnpm security overrides** (in `pnpm-workspace.yaml`): the transitive `esbuild` is forced to
`>=0.28.1` (high-severity RCE advisory in `<0.28.1`, pulled via Vite) and `form-data` to
`>=4.0.6` (CRLF-injection advisory, pulled via jsdom/Vitest, dev/test only).

---

## Supply-chain controls (what runs in CI)

Exactly six controls are wired today, across `.github/workflows/ci.yml` and `release.yml`:

1. **CycloneDX SBOM** — `scripts/generate_sbom.sh` runs
   `uv export --no-dev --format requirements-txt --no-emit-workspace`, then
   `cyclonedx-py requirements` into `sbom/python.cdx.json` (uploaded as a CI artifact).
   **Covers Python runtime dependencies only.** JS/TS and Rust/Tauri are **not** in any SBOM
   today — an honest gap.
2. **pip-audit** — `uv run pip-audit --skip-editable`; Python vulnerability audit against the
   PyPI advisory DB.
3. **pnpm audit** — `pnpm audit --audit-level high`; JS vulnerability audit.
4. **Register drift check** — `scripts/check_supply_chain_drift.sh` (PR only); **fails the PR**
   if a manifest or lockfile changed without a corresponding edit to this register.
5. **detect-secrets** — `scripts/scan_secrets.sh` against the committed `.secrets.baseline`;
   secret scan.
6. **cosign signing** — in `ci.yml`, a signing smoke test (`scripts/signing_smoke.sh`) that
   signs and verifies a test artifact with an **offline ephemeral key** (`--tlog-upload=false`,
   no Fulcio/Rekor); in `release.yml`, **keyless Sigstore signing** (GitHub OIDC) of `dist/*`
   and the SBOM, with the signatures and certs attached to the release.

**Not in CI:** there is **no** syft, Trivy, Grype, or SPDX SBOM/scanner, **no** OpenTelemetry,
and **no** Rust/Tauri build. The SBOM is CycloneDX (Python-only) and vulnerability scanning is
pip-audit (Python) plus pnpm audit (JS).

---

## How this register is maintained

The register is kept honest by the **drift check** (control 4 above): any PR that edits a
manifest (`pyproject.toml`, `package.json`) or lockfile (`uv.lock`, `pnpm-lock.yaml`) must edit
this file in the same change, or CI fails. When a dependency is added, removed, or upgraded,
update the relevant table here and regenerate the SBOM in the same PR.
