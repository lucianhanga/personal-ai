#!/usr/bin/env bash
# Scan all tracked files for secrets not present in the baseline.
# Usage: scripts/scan_secrets.sh   (run via `make secrets`, and in CI)
set -euo pipefail

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; RESET=$'\033[0m'

if [ ! -f .secrets.baseline ]; then
  printf '%s\n' "${RED}FAIL: .secrets.baseline not found. Run: uv run detect-secrets scan > .secrets.baseline${RESET}"
  exit 1
fi

# detect-secrets-hook exits non-zero if any tracked file contains a secret not in the baseline.
if uv run detect-secrets-hook --baseline .secrets.baseline $(git ls-files); then
  printf '%s\n' "${GREEN}OK: no new secrets detected.${RESET}"
else
  printf '%s\n' "${RED}FAIL: potential secret detected (see above). Remove it or, if a false positive, run 'uv run detect-secrets scan > .secrets.baseline' and review.${RESET}"
  exit 1
fi
