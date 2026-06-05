# Toolchain & Monorepo

How the PersonalAI monorepo is wired: the uv (Python) and pnpm (JS/TS) workspaces, the `Makefile`
targets, and the CI jobs. This reflects the **actual** configuration in the repo today. For the
contributor workflow (branching, commits, PRs) and onboarding, see
[CONTRIBUTING.md](../../CONTRIBUTING.md) and [ONBOARDING.md](../ONBOARDING.md) — this doc does not
repeat them.

## Source of truth

- Python workspace + tool config: `pyproject.toml`
- Architecture enforcement: `.importlinter`
- Task runner: `Makefile`
- CI: `.github/workflows/ci.yml`
- JS workspace: `package.json` + `pnpm-workspace.yaml` *(declared; JS apps are placeholders until
  M0-6)*

## Python workspace (uv)

`pyproject.toml` defines a **uv virtual workspace** of the modular monolith's Python packages:

```toml
[tool.uv.workspace]
members = ["contracts", "core", "apps/backend"]
```

| Member | Package | Role |
|---|---|---|
| `contracts` | `personalai_contracts` | Stable core API: ports (M0-2), schemas (M0-3). Innermost layer. |
| `core` | `personalai_core` | Orchestration, gateway, validation (depends only on contracts). |
| `apps/backend` | `personalai_backend` | FastAPI wiring; DI picks adapters from registries (M0-4). |

Dev tools are pinned in `[dependency-groups] dev`: `ruff>=0.6`, `mypy>=1.11`, `pytest>=8.2`,
`pytest-cov>=5.0`, `import-linter>=2.0`. Install everything with `uv sync` (or `make setup`,
which also runs `pnpm install`). CI uses `uv sync --all-packages`.

The dependency direction between members is enforced by import-linter — see
[coding-standards.md](./coding-standards.md#1-hexagonal-dependency-direction).

## JS/TS workspace (pnpm)

A separate **pnpm workspace** holds the frontend apps. Per the planned layout
([§22.3](../architecture/PersonalAI-Architecture-Research.md#223-suggested-repository-shape-isolation-by-package))
these are `apps/ui` (Tauri + SPA) and `apps/extension` (MV3 browser extension). They are
**placeholders until M0-6** — the CI lint step runs `pnpm -r --if-present lint`, which is a no-op
until each workspace defines a `lint` script. The pnpm version is read from the `packageManager`
field in `package.json`.

## Makefile targets

Run `make help` for the live list. Current targets:

| Target | Runs | Purpose |
|---|---|---|
| `make setup` | `uv sync` + `pnpm install` | Install Python and JS dependencies. |
| `make lint` | `uv run ruff check .` | Ruff lint (Python). |
| `make format` | `uv run ruff format .` | Ruff format (Python). |
| `make typecheck` | `uv run mypy contracts core apps/backend` | mypy strict type check. |
| `make test` | `uv run pytest` | Python tests with coverage. |
| `make arch` | `uv run lint-imports` | Enforce hexagonal dependency direction. |
| `make schemas` | `scripts/generate_schemas.py` | Regenerate canonical JSON Schema (M0-3). |
| `make run-backend` | `python -m personalai_backend` | Run the loopback backend (M0-5). |
| `make sbom` | `scripts/generate_sbom.sh` | Generate the CycloneDX SBOM (M0-8). |
| `make audit` | `pip-audit` + `pnpm audit` | Vulnerability scan, blocks on high/critical (M0-8). |
| `make drift` | `scripts/check_supply_chain_drift.sh` | Fail if deps changed without updating the register (M0-8). |
| `make js` | `js-typecheck` + `js-test` + `js-lint` | All JS/TS checks. |
| `make check` | `lint` + `typecheck` + `test` + `arch` + `js` | All checks (Python + JS) — run before a PR. |

## CI jobs

`.github/workflows/ci.yml` runs on `push` and `pull_request` against `main`, with concurrency
cancellation per ref and `contents: read` permissions. Three jobs run in parallel:

| Job | Name | Steps |
|---|---|---|
| `repo-health` | Repository health | Asserts the required governance files exist (README, LICENSE, SECURITY, CONTRIBUTING, CHANGELOG, the architecture report, threat model, dependency policy, supply-chain register, onboarding). Fails if any are missing. |
| `python` | Python (lint, types, tests, architecture) | Install uv -> Python 3.12 -> `uv sync --all-packages` -> `ruff check .` -> `ruff format --check .` -> `mypy contracts core apps/backend` -> `lint-imports` -> `pytest` -> upload `coverage.xml` artifact. |
| `js` | JS/TS (install, lint) | pnpm + Node 22 -> `pnpm install` -> `pnpm -r --if-present typecheck` -> `... test` -> `... lint`. |
| `supply-chain` | Supply chain (SBOM, audit, drift) | Generate CycloneDX SBOM (artifact) -> `pip-audit` -> `pnpm audit --audit-level high` -> drift check (PR only). |

The first three jobs (`Repository health`, `Python ...`, `JS/TS ...`) are **required status
checks** on `main` (M0-7). The `supply-chain` job runs on every PR/push and fails visibly on
findings; it is not yet a required check (the audits depend on the advisory-DB network) and can be
promoted later. Release signing (Sigstore/cosign) is added in **M0-9**.

The CI `python` job mirrors `make check` (Python portion) plus `ruff format --check`, so running
`make check && uv run ruff format --check .` locally reproduces the gate.

## Running checks locally

```bash
make setup     # once: uv sync + pnpm install
make check     # lint + types + tests (coverage) + architecture
```

Or invoke tools directly: `uv run ruff check .`, `uv run ruff format .`,
`uv run mypy contracts core apps/backend`, `uv run pytest`, `uv run lint-imports`,
`pnpm -r --if-present lint`. The coverage gate (`fail_under = 90`) and report locations are
documented in [coding-standards.md §8](./coding-standards.md#8-testing--coverage).

## Related

- [Coding standards & conventions](./coding-standards.md)
- [Contracts & ports reference](../reference/contracts-and-ports.md)
- [CONTRIBUTING.md](../../CONTRIBUTING.md) — workflow, branching, commits, PRs
- [ONBOARDING.md](../ONBOARDING.md) — orientation and mental model

## Last updated notes

- 2026-06-05: Initial toolchain doc for the M0-1 monorepo.
- 2026-06-05: M0-8 — added SBOM (`make sbom`), vulnerability audit (`make audit`), and the
  supply-chain drift check (`make drift`) plus the `supply-chain` CI job; documented the required
  status checks (M0-7) and the runnable backend / schema targets.
