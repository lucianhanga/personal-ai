#!/usr/bin/env bash
# Fail if dependency manifests changed without updating the supply-chain register.
# Usage: scripts/check_supply_chain_drift.sh [base-ref]   (default: origin/main)
set -euo pipefail

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[0;33m'; RESET=$'\033[0m'

BASE_REF="${1:-origin/main}"
REGISTER="docs/supply-chain/SUPPLY-CHAIN.md"

if ! git rev-parse --verify --quiet "${BASE_REF}" >/dev/null; then
  printf '%s\n' "${YELLOW}warning: base ref '${BASE_REF}' not found; skipping drift check${RESET}"
  exit 0
fi

changed="$(git diff --name-only "${BASE_REF}...HEAD")"

dep_changed=false
register_changed=false
while IFS= read -r f; do
  [ -z "${f}" ] && continue
  case "${f}" in
    pyproject.toml|*/pyproject.toml|uv.lock|package.json|*/package.json|pnpm-lock.yaml)
      dep_changed=true ;;
    "${REGISTER}")
      register_changed=true ;;
  esac
done <<< "${changed}"

if [ "${dep_changed}" = true ] && [ "${register_changed}" = false ]; then
  printf '%s\n' "${RED}FAIL: dependency manifests changed but ${REGISTER} was not updated.${RESET}"
  printf '%s\n' "${YELLOW}Update the supply-chain register in the same PR (see DEPENDENCY-POLICY).${RESET}"
  exit 1
fi

printf '%s\n' "${GREEN}OK: supply-chain drift check passed.${RESET}"
