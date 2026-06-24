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

**Why this matters / how to apply:** When asked to add frontend tests or harden CI, propose adding ESLint + vitest coverage gate (they still don't exist as of the Pre-M8 Hardening sprint, verified 2026-06-12). The cookie/CSRF transport is still NOT exercised by any test (Login render IS tested now via Login.test.tsx + App.test.tsx 401->Login; but no test asserts `X-CSRF-Token`/`credentials:"include"` are sent, and logout->401 re-gate is untested) — recommend `api.test.ts` asserting credentials+CSRF headers before hosted deploy.

**Pre-M8 Hardening sprint outcomes (verified 2026-06-12, code-read):**
- C1 SSE parser FIXED + tested: `streamChat` in `api.ts` now guards `JSON.parse` (skips malformed frames) and flushes the trailing frame after the read loop (`buffer += decoder.decode(); processFrame(buffer)`). This was the "no answer" root cause. `api.test.ts` covers deltas/error/malformed/final-frame.
- A6 (#229) TraceItem FIXED + tested: union extended with `plan|critique|verification` plus `role`+`verdict` fields; `MessageDetails.tsx` renders them and has a GENERIC FALLBACK (`details-other`) for unknown future kinds. Tested in `MessageDetails.test.tsx`.
- A4 (#227) unified SSE wire format: parser reads only `delta`/`thinking` and ignores `done`/`finish_reason` — no UI assumption on per-chunk done. NOTE: `e2e/chat.spec.ts` CHAT_SSE fixture is STALE (still old per-chunk `done`/`finish_reason` format) — harmless but should be updated.
- Verdict given: GO for local M8; go-with-fixes for hosted.

**Side panel = unified Activity timeline (#374):** `SidePanel.tsx` renders `ActivityTimeline.tsx` as its centerpiece — one collapsible group per Q/A turn, newest on top, each turn's spine listing context+tools+reasoning in chronological order. It REUSES `ToolIO` (call+result pairing, egress allow-on-deny), `ContextComposition` (`collapsible={false}`), and the agent color code (`agentColors.ts` + violet tool / green ok / red err / #4a90d9 context accent). To avoid double-rendering the live context composition, `ContextMeter` is now called with `context={null}` (window-usage + chat-totals only). Per-turn timestamps come from `ChatMessage.created_at` (ISO; absent on the in-flight turn -> "just now"/live). A blocked tool now surfaces an Allow button in BOTH the transcript Details and the timeline, so egress-allow tests must use `getAllByTestId`, not `getByTestId`. Filter chips (All/Tools/Reasoning/Context) hide non-matching nodes; a turn with no visible nodes is hidden.

**Still-open (deferred, NOT blockers for local M8):** H1 — `fetchSession` non-401 errors (500/503) map to "error" -> renders app, masking real failures (App.tsx, by-design comment). H2 — legacy token `<input>` in `Chat.tsx` coexists with cookie login (fine locally since local uses token; gate on `auth_kind!=="cookie"` before hosted). Chat.tsx still ~619 lines, ~30 useState + 6 inline useEffect, no custom hooks extracted (decomposition into child components is clean though).
