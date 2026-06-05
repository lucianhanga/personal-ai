# PersonalAI desktop shell (Tauri 2)

This wraps the React SPA (`../`) in a native window via Tauri. It uses Tauri's **capability-based
permissions** (deny-by-default; see `capabilities/default.json`) and a strict CSP.

> **Scaffold status (M0-6):** these files are not built in CI because the GitHub runners and this
> dev environment do not have the Rust toolchain provisioned. Build and verify locally on a
> machine with Rust + the Tauri system dependencies. Desktop packaging is hardened in M11.

## Build locally

Prerequisites: Rust (`rustup`), the platform's Tauri prerequisites
(https://tauri.app/start/prerequisites/), and the Tauri CLI:

```bash
# from apps/ui
pnpm add -D @tauri-apps/cli         # or: cargo install tauri-cli
pnpm tauri dev                      # launches the native window (loads the Vite dev server)
pnpm tauri build                    # produces a signed-able desktop bundle
```

Add app icons before bundling: `pnpm tauri icon path/to/icon.png` (writes `icons/`).

The window loads the SPA from `../dist` (production) or `http://localhost:5173` (dev), and the SPA
talks only to the local backend over loopback.
