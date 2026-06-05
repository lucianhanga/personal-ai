# apps/ui (`@personalai/ui`)

The PersonalAI **desktop/web UI**: a **React** SPA (Vite + TypeScript) wrapped by a **Tauri**
desktop shell (`src-tauri/`). Framework decision recorded in
[ADR-0006](../../docs/architecture/adr/0006-ui-react-tauri.md).

## Develop (web)

```bash
pnpm --filter @personalai/ui dev       # Vite dev server at http://localhost:5173
pnpm --filter @personalai/ui build     # typecheck + production build to dist/
pnpm --filter @personalai/ui preview   # serve the built app at http://localhost:4173
```

The SPA calls the local backend at `VITE_API_BASE` (default `http://127.0.0.1:8765`) and renders
backend connectivity, a local/remote provider badge, and the local-first security note. Run the
backend with `make run-backend` (see [backend API docs](../../docs/reference/backend-api.md)).

## Test

```bash
pnpm --filter @personalai/ui test       # Vitest component tests (jsdom)
pnpm --filter @personalai/ui test:e2e   # Playwright e2e (builds + previews + drives Chromium)
```

Playwright e2e mocks the backend `/health` so it is deterministic and needs no Python backend.
First run locally: `pnpm --filter @personalai/ui exec playwright install chromium`.

## Desktop (Tauri)

See [`src-tauri/README.md`](./src-tauri/README.md). Requires the Rust toolchain; not built in CI.
