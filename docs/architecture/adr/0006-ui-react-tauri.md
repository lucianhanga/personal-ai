# 6. UI: React SPA wrapped by a Tauri desktop shell

- Status: Accepted
- Date: 2026-06-05

## Context

PersonalAI needs a desktop/web UI that is secure, cross-platform, and reuses one codebase for the
web and desktop surfaces. The architecture (ADR-0001, §13) already chose Tauri for the shell; the
open question was the SPA framework (React vs Svelte).

## Decision

Use **React** (Vite + TypeScript) for the SPA, wrapped by a **Tauri 2** desktop shell.

- React: largest ecosystem, strongest Tauri and Playwright support, broadest contributor/AI
  familiarity. Svelte is leaner but a smaller ecosystem for this project's needs.
- Tauri: capability-based permissions (deny-by-default), native WebView (small footprint), strict
  CSP — matches the security-first posture better than Electron.
- Testing: **Vitest** + Testing Library for component tests; **Playwright** for e2e (the user
  required Playwright). E2e mocks the backend `/health` for determinism.

## Consequences

- Positive: one SPA serves web and desktop; strong typing end-to-end with the Zod contracts;
  security-friendly shell.
- Negative: the Tauri build needs the Rust toolchain + system WebView deps, so it is **not built in
  CI** yet (no Rust on the runners); the SPA and its tests are fully CI-verified, and the Tauri
  shell is a documented local/release build (hardened in M11). Native WebView differences across
  platforms remain a known risk (architecture §19).

## Alternatives considered

- Svelte — leaner/faster, smaller ecosystem; viable, not chosen.
- Electron — larger attack surface (Node in renderer), bigger footprint; rejected (ADR-0001).
