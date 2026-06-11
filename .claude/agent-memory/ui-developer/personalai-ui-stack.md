---
name: personalai-ui-stack
description: PersonalAI SPA frontend stack, tooling weaknesses, and durable architecture facts for apps/ui
metadata:
  type: project
---

PersonalAI SPA lives at `apps/ui` — React 19 + Vite 6 + TypeScript + Vitest 4 + Playwright. pnpm workspace; CI in `.github/workflows/ci.yml` (`js` job + `ui-e2e` job).

**Tooling weaknesses (durable, verify before relying):**
- No ESLint. `package.json` `lint` script is just `tsc --noEmit` (alias of `typecheck`). So CI `js` job runs tsc twice; no react-hooks / no-floating-promises linting.
- No coverage tooling installed and no coverage threshold/gate anywhere. `@vitest/coverage-*` is absent.
- Playwright runs Desktop Chrome only (`playwright.config.ts`) — no mobile/responsive viewport project.

**Auth model (post #217 cookie/CSRF migration):** `app_mode` local (zero-login dev) vs hosted (cookie login + double-submit CSRF). `api.ts` `authHeaders()` sends bearer token (if any) + `X-CSRF-Token` read from `pai_csrf` cookie; all calls send `credentials:"include"`. Backend resolves cookie-first then bearer. `App.tsx` gates: session loading -> Login on clean 401 -> render-app on error. XSS posture is strong: `Markdown.tsx` has no dangerouslySetInnerHTML and no rehype-raw, pinned by tests.

**Why this matters / how to apply:** When asked to add frontend tests or harden CI, propose adding ESLint + vitest coverage gate (they don't exist). The cookie/CSRF path is NOT exercised by any test (all API fns mocked; e2e uses bearer token via addInitScript) — recommend `api.test.ts` asserting credentials+CSRF headers. `streamChat` SSE parser in `api.ts` has no unit tests and does not flush the trailing buffer after the read loop nor guard JSON.parse — suspected cause of "no answer" turns. M8 multi-agent trace: `TraceItem.kind` is a closed union with no agent/role discriminator and no verdict kind; `appendTrace` merges consecutive reasoning regardless of agent.
