# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/) and the project follows
[Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

**Versioning policy (pre-1.0):** `MAJOR` stays `0` until the first stable release; `MINOR` bumps as
each milestone (M1, M2, …) lands; `PATCH` bumps for fixes/UX tweaks between milestones. The HTTP API
is versioned independently in the URL path (`/api/v1`) and surfaced as `info.version` in the
generated OpenAPI document.

## [Unreleased]

## [0.6.0] — 2026-06-09

Milestones **M0–M6** complete.

### Added
- **M6 — single-agent loop**: the model autonomously calls tools through the gateway and **streams
  reasoning + answer** token-by-token (tool calls parsed from the provider stream, Ollama + OpenAI).
  Built-in `web_search` (DuckDuckGo); ordered per-message **Details** (reasoning + tool calls)
  persisted and shown collapsibly; in-progress markers; concurrent per-chat streaming; rename chats;
  per-chat **Activity** + **App logs**; context-usage meter; bounded `num_ctx`.
- **M5 — Tool/MCP gateway**: permissions, network egress allowlist, JSON-Schema I/O validation, risk
  approval, timeout, append-only audit; built-in calculator + http_fetch.
- **M4 — memory**: per-chat short-term summary + cross-chat long-term memory (view/edit/erase);
  incognito chats.
- **M3 — files + RAG**: ingestion → pgvector retrieval with citations.
- **M2 — provider portability**: remote OpenAI-compatible provider behind the same seam.
- **M1 — local chat**: streaming chat over local Ollama models.
- **M0 — skeleton**: hexagonal contracts/core, CI, structured outputs, security primitives,
  architecture research, roadmap, supply-chain/security/threat-model docs, repo scaffolding.
- **Versioning**: project semver (`VERSION` + this changelog) and a versioned HTTP API.

### Changed
- The HTTP API is now served under **`/api/v1`** (the `/health` and `/version` infrastructure
  endpoints stay unversioned); OpenAPI `info.version` reflects the project version.

[Unreleased]: https://github.com/lucianhanga/personal-ai/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/lucianhanga/personal-ai/releases/tag/v0.6.0
