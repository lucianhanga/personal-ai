# PersonalAI developer task runner.
# Python is managed by uv; JS by pnpm. See CONTRIBUTING.md.

.DEFAULT_GOAL := help
.PHONY: help setup lint format typecheck test arch schemas run-backend sbom audit drift js-install js-typecheck js-test js-lint js check

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install Python (uv) + JS (pnpm) dependencies
	uv sync
	pnpm install

lint: ## Ruff lint (Python)
	uv run ruff check .

format: ## Ruff format (Python)
	uv run ruff format .

typecheck: ## mypy type check (Python)
	uv run mypy contracts core apps/backend

test: ## Run Python tests with coverage
	uv run pytest

arch: ## Enforce hexagonal dependency direction (import-linter)
	uv run lint-imports

schemas: ## Regenerate canonical JSON Schema artifacts (schemas/json)
	uv run python scripts/generate_schemas.py

run-backend: ## Run the loopback backend (set PERSONALAI_AUTH_TOKEN for protected routes)
	uv run python -m personalai_backend

sbom: ## Generate a CycloneDX SBOM of runtime deps (sbom/python.cdx.json)
	bash scripts/generate_sbom.sh

audit: ## Vulnerability scan (pip-audit + pnpm audit, blocks on high/critical)
	uv run pip-audit
	pnpm audit --audit-level high

drift: ## Fail if dependency manifests changed without updating SUPPLY-CHAIN.md
	bash scripts/check_supply_chain_drift.sh

js-install: ## Install JS workspace dependencies
	pnpm install

js-typecheck: ## Typecheck JS/TS workspaces
	pnpm -r --if-present typecheck

js-test: ## Test JS/TS workspaces (Vitest)
	pnpm -r --if-present test

js-lint: ## Lint JS workspaces
	pnpm -r --if-present lint

js: js-typecheck js-test js-lint ## Run all JS/TS checks

check: lint typecheck test arch js ## Run all checks (Python + JS)
