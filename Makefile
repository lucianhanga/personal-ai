# PersonalAI developer task runner.
# Python is managed by uv; JS by pnpm. See CONTRIBUTING.md.

.DEFAULT_GOAL := help
.PHONY: help setup lint format typecheck test arch js-install js-lint check

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

js-install: ## Install JS workspace dependencies
	pnpm install

js-lint: ## Lint JS workspaces (placeholders until M0-6)
	pnpm -r --if-present lint

check: lint typecheck test arch ## Run all Python checks (lint, types, tests, architecture)
