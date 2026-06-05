# Coding Standards & Conventions

Actionable rules for writing PersonalAI code so that changes stay modular, typed, validated, and
testable. These reflect the **actual** tool configuration in `pyproject.toml`, `.importlinter`,
and `.github/workflows/ci.yml`. Where a rule depends on something not yet built, it is marked
*planned (Mx)*.

## Source of truth

- Tooling: `pyproject.toml` (ruff, mypy, pytest, coverage), `.importlinter`, `Makefile`
- CI: `.github/workflows/ci.yml`
- Architecture rules: [ADR-0001](../architecture/adr/0001-modular-monolith-hexagonal.md),
  [ADR-0003](../architecture/adr/0003-structured-output-first.md)
- Commit/PR workflow: [CONTRIBUTING.md](../../CONTRIBUTING.md)

## 1. Hexagonal dependency direction

Dependencies always point **inward to `personalai_contracts`**
([ADR-0001](../architecture/adr/0001-modular-monolith-hexagonal.md)):

```
personalai_backend  ->  personalai_core  ->  personalai_contracts
```

- `personalai_contracts` must not import `core` or `backend`.
- `personalai_core` must not import `backend`.
- Adapters never import each other; the core never imports a concrete adapter.

This is enforced by **import-linter** (`.importlinter`, contract type `layers`). The check runs
as `make arch` / `uv run lint-imports` locally and as the "Architecture (import-linter)" CI step.
A violation fails the build — it is not a style suggestion.

## 2. Structured-output-first

Every boundary carries validatable data, not free text
([ADR-0003](../architecture/adr/0003-structured-output-first.md)):

- JSON Schema is the canonical interchange; Pydantic (Python) authors/validates it. *(Schema
  layer is M0-3 — until then, ports carry typed dataclasses and `json_schema` passthrough.)*
- Validate at **every** hop (model -> backend, tool -> backend, backend -> UI).
- On invalid output: bounded repair retry -> deterministic repair if safe -> **fail closed**.
- Never execute an unvalidated tool call. `ToolResult` is fail-closed (`ok=False` on error).
- Schemas are versioned (`$id` + semver); the validator supports N / N-1.

## 3. Typing under mypy strict

`[tool.mypy]` runs with `strict = true`, plus `warn_unused_configs`, `warn_redundant_casts`,
`warn_unused_ignores`, `show_error_codes`. Target is Python 3.12.

- Annotate everything; no implicit `Any`. `strict` forbids untyped defs.
- `# type: ignore` must be specific and justified — `warn_unused_ignores` flags stale ones.
- Put `from __future__ import annotations` at the top of every module (matches existing code).
- Use modern generics: PEP 695 syntax (`class Repository[T](Protocol)`), `X | None` over
  `Optional[X]`.
- Use `collections.abc.Mapping` / `Sequence` for read-only inputs (variance-friendly); reserve
  `dict` / `list` for concrete internal state.
- Run locally with `make typecheck` (`uv run mypy contracts core apps/backend`).

## 4. Ports, Protocols, and value objects

- Ports are `typing.Protocol` classes decorated with `@runtime_checkable` so adapters satisfy
  them **structurally** (no inheritance) and tests can assert `isinstance(adapter, Port)`.
- Value objects are `@dataclass(frozen=True)` — immutable. Use
  `field(default_factory=dict)` for mutable defaults.
- Enums are `enum.StrEnum` (e.g. `Role`, `ModalityKind`) so values serialize as plain strings and
  compare to strings directly.
- Keep ports minimal and OpenAI-compatible where applicable; omit speculative methods (streaming
  was deliberately left out until M1).
- Full inventory: [contracts-and-ports.md](../reference/contracts-and-ports.md).

## 5. Async conventions

- I/O-bound methods are `async def` (`generate`, `embed`, `retrieve`, all storage ops, `parse`,
  `run`, `invoke`).
- Cheap, CPU-only lookups stay synchronous (`capabilities`, `can_handle`, `node`).
- Do not block the event loop inside `async def`; offload blocking calls appropriately when real
  adapters land.
- Tests drive coroutines with `asyncio.run(...)` — see section 8.

## 6. Naming

- Packages/modules: `snake_case`; first-party packages are `personalai_contracts`,
  `personalai_core`, `personalai_backend` (declared in `[tool.ruff.lint.isort] known-first-party`
  and `[tool.mypy] mypy_path`).
- Classes: `PascalCase`; ports are nouns describing the role (`ModelProvider`, `Retriever`).
  Fakes are prefixed `Fake*` (stateful behaviour) or `InMemory*` / `Echo*` (storage/passthrough).
- Adapter packages live one-per-folder under their seam (`/providers/ollama`, `/storage/postgres`,
  `/tools/<tool>`), per the planned layout in
  [§22.3](../architecture/PersonalAI-Architecture-Research.md#223-suggested-repository-shape-isolation-by-package).

## 7. Lint & format (Ruff)

`[tool.ruff]` is the single linter/formatter (replaces black/isort/flake8):

- `line-length = 100`, `target-version = "py312"`.
- Rule sets: `E`, `F`, `I` (isort), `UP` (pyupgrade), `B` (bugbear), `SIM`, `C4`, `PTH`
  (prefer `pathlib` over `os.path`).
- `make lint` -> `uv run ruff check .`; `make format` -> `uv run ruff format .`.
- CI runs both `ruff check .` and `ruff format --check .` — formatting drift fails the build.

## 8. Testing & coverage

`[tool.pytest.ini_options]`:

- `addopts = "-ra -q --import-mode=importlib --cov --cov-report=term-missing --cov-report=xml"`.
  `--import-mode=importlib` means tests resolve packages from the installed/`src` layout — do not
  rely on implicit `sys.path` or `__init__.py` test packages.
- `testpaths = ["contracts/tests", "core/tests", "apps/backend/tests"]`.
- Coverage: `branch = true`; **`fail_under = 90`** (a hard gate; raised as real logic lands, see
  M0-7). `exclude_also` ignores `if TYPE_CHECKING:`, `raise NotImplementedError`, and `...`.

Patterns to follow (from `contracts/tests/test_ports.py`):

- Assert the structural contract first: `assert isinstance(adapter, ThePort)`.
- Drive async methods with `asyncio.run(...)` — the suite intentionally has **no** async
  test-plugin dependency. Keep it that way unless an ADR changes it.
- Reuse the reference fakes from `personalai_contracts.testing` for collaborators.

Coverage report: `pytest` writes `coverage.xml` (Cobertura) at the repo root and prints
`term-missing` to the console. There is no HTML report configured. CI runs `uv run pytest`; it
does not currently upload coverage to an external service.

Run all checks at once with `make check` (lint + typecheck + test + arch).

## 9. Commits & PRs

Follow [CONTRIBUTING.md](../../CONTRIBUTING.md): GitHub flow, protected `main`,
[Conventional Commits](https://www.conventionalcommits.org/) (`feat`, `fix`, `docs`, `chore`,
`refactor`, `test`, `build`, `ci`, `perf`, `security`), e.g.
`feat(contracts): add ModelProvider port`. If a contract/schema changes, bump its version and add
an ADR when it affects a stable port or message contract. Update docs to match behaviour.

## Common mistakes

- Importing a sibling adapter or importing outward — caught by import-linter.
- Adding a method to a port to make one adapter work (widening the core) instead of keeping the
  variation inside the adapter — see the golden rule in
  [contracts-and-ports.md](../reference/contracts-and-ports.md#how-to-add-an-adapter).
- Mutable dataclass defaults without `field(default_factory=...)`.
- Leaving an unused `# type: ignore` (fails `warn_unused_ignores`).
- Forgetting `ruff format` before pushing (CI runs `--check`).
- Dropping below the 90% coverage gate when adding code.

## Related

- [Contracts & ports reference](../reference/contracts-and-ports.md)
- [Toolchain & monorepo](./toolchain.md)
- [CONTRIBUTING.md](../../CONTRIBUTING.md)

## Last updated notes

- 2026-06-05: Initial standards aligned to the M0 toolchain. Schema authoring (M0-3) and the
  registry/DI layer (M0-4) referenced as upcoming.
