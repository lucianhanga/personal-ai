# Contributing to PersonalAI

Thanks for working on PersonalAI. This repo uses **GitHub flow** with a protected `main`.

## Workflow (GitHub flow)

1. **Pick a ticket** and set its Project status to **In Progress** (and assign yourself).
2. **Create the branch _linked to the issue_** (so it shows under the issue's Development
   section and the issue auto-closes on merge) — prefer GitHub's native linked branch over a
   plain `git checkout -b`:
   ```bash
   gh issue develop <issue-number> --repo lucianhanga/personal-ai \
     --name <type>/<short-description> --base main
   git fetch origin && git checkout <type>/<short-description>
   ```
   Branch name `<type>` mirrors the commit types below, e.g. `feat/contracts-model-provider`.
3. **Commit** using [Conventional Commits](https://www.conventionalcommits.org/):
   ```
   <type>(<scope>): <summary>
   ```
   Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `build`, `ci`, `perf`, `security`.
   Example: `feat(contracts): add ModelProvider port and capability schema`.
4. **Open a PR** into `main`. Fill in the PR template. Link the issue (`Closes #NN`).
5. **CI must pass.** `main` is protected: no direct pushes, no force-push, no deletion.
6. **Merge** via PR (squash preferred for a linear, readable history).
7. **Set the ticket status to Done** when the PR merges.

> `main` requires a pull request to merge. Self-merge is permitted for the solo maintainer,
> but the PR + CI gate still applies.

## Local development

Python is managed by **uv**; JS by **pnpm**. Common tasks are in the `Makefile`:

```bash
make setup       # uv sync + pnpm install
make check       # ruff lint + mypy + pytest (coverage) + import-linter
make test        # pytest with coverage
make arch        # enforce hexagonal dependency direction (import-linter)
```

Or directly: `uv run ruff check .`, `uv run mypy ...`, `uv run pytest`, `uv run lint-imports`,
`pnpm -r --if-present lint`.

## Definition of Done

- Code matches surrounding style; no secrets committed.
- Tests added/updated where applicable; CI green.
- **If dependencies changed:** [`SUPPLY-CHAIN.md`](./docs/supply-chain/SUPPLY-CHAIN.md) and the
  SBOM are updated in the **same PR** (see [Dependency Policy](./docs/policies/DEPENDENCY-POLICY.md)).
- **If a contract/schema changed:** version bumped and an [ADR](./docs/architecture/adr/) added
  if it affects a stable port or message contract.
- Docs updated to match behavior.

## Architecture rules (keep changes modular)

PersonalAI is hexagonal (ports & adapters + registries). Honor the **golden rule**:

> **New capability = a new adapter behind an existing port + a registry entry + a schema.
> The core (`/contracts`, orchestrator, gateway, storage interfaces) stays stable.**

- Adapters never import each other; the core never imports a concrete adapter.
- Dependencies point **inward to `/contracts`**.
- See [§22 Modular Implementation Roadmap](./docs/architecture/PersonalAI-Architecture-Research.md#22-modular-implementation-roadmap).

## Security

- Treat all external input as untrusted. See [SECURITY.md](./SECURITY.md) and the
  [Threat Model](./docs/architecture/THREAT-MODEL.md).
- Never commit secrets. Report vulnerabilities privately (see SECURITY.md).

## Issues & project tracking

Work is tracked on the GitHub Project board. Use the issue templates (Task / Feature / Bug).
Milestones map to the roadmap (M0, M1, …).
