# Dependency & Supply-Chain Policy

PersonalAI is **open-source-first but verified**. Trust in our dependencies is a hard
requirement, not a nice-to-have. This policy governs what we may depend on and how.

## 1. Acceptance criteria (all required)

A dependency may be adopted only if it has:

1. **Identifiable, reputable maintainer/organization** — a known org (Microsoft, Google,
   Meta, Anthropic, OpenAI, Mozilla, Hugging Face, Docker, Cloudflare, LangChain, Ollama,
   Supabase, PostgreSQL, CNCF/Apache projects, or a clearly identifiable maintainer with track
   record). **No anonymous accounts, no unclear provenance.**
2. **An OSI-approved (or clearly compatible) license**, recorded and compatible with Apache-2.0.
3. **Demonstrated maturity** — meaningful adoption, recent activity, responsive maintenance.
4. A documented **reason for inclusion** and at least one **safer alternative** considered.
5. **No known unpatched critical/high vulnerabilities** at adoption time.

Each adopted dependency is recorded in
[`docs/supply-chain/SUPPLY-CHAIN.md`](../supply-chain/SUPPLY-CHAIN.md).

## 2. Prohibited

- Obscure libraries, anonymous GitHub users, unmaintained or abandoned packages.
- Packages with unclear provenance, typosquat-prone names, or no license.
- Transitively pulling unvetted packages without review.

## 3. Pinning & integrity

- **Pin exact versions** and record integrity hashes (lockfiles committed).
- Prefer immutable references (tags/commits) for tools and MCP servers.
- Configure registries to prevent **dependency confusion** (scope private packages).

## 4. SBOM & scanning

- Generate a **CycloneDX SBOM** on every build. The SBOM currently covers **Python runtime
  dependencies only** — JS/TS and Rust/Tauri are not yet included.
- Run **vulnerability scanning** — `pip-audit` (Python) and `pnpm audit` (JS) — in CI; block on
  new critical/high findings.
- The human-readable register and the machine SBOM must agree (drift check in CI).

## 5. MCP servers & tools (extra scrutiny)

Third-party MCP servers and tools are treated as **untrusted code**:

1. Provenance + license check.
2. Pin version **and** hash.
3. Review declared permissions (deny-by-default).
4. First run **sandboxed with network egress OFF**.
5. Promote to enabled only after explicit approval, scoped per workspace/project.

User-developed GitHub tools are third-party until signed — **author trust ≠ code trust**.

## 6. Updates

- Updates land via PR, with SBOM + register updated in the same change.
- Security updates are prioritized; breaking updates get an ADR if they affect contracts.

## 7. Releases

- Releases are **signed** (Sigstore/cosign) and ship an SBOM.
- Reproducible builds are pursued where feasible.
