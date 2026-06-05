#!/usr/bin/env bash
# Scan all tracked files for secrets not present in the baseline, plus a targeted check for
# credentials embedded in URLs (which also covers lockfiles).
# Usage: scripts/scan_secrets.sh   (run via `make secrets`, and in CI)
set -euo pipefail

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; RESET=$'\033[0m'

if [ ! -f .secrets.baseline ]; then
  printf '%s\n' "${RED}FAIL: .secrets.baseline not found. Run: uv run detect-secrets scan > .secrets.baseline${RESET}"
  exit 1
fi

status=0

# 1) detect-secrets: blocks secrets not present in the baseline.
if ! uv run detect-secrets-hook --baseline .secrets.baseline $(git ls-files); then
  printf '%s\n' "${RED}FAIL: potential secret detected by detect-secrets (see above).${RESET}"
  status=1
fi

# 2) Basic-auth-in-URL (user:pass@host) across ALL tracked files, including lockfiles, which
#    detect-secrets may skip. Exclude self and the baseline to avoid matching the pattern itself.
basic_auth_re='://[^/[:space:]"'"'"']+:[^/[:space:]"'"'"'@]+@'
if git grep -nIE "${basic_auth_re}" -- ':!.secrets.baseline' ':!scripts/scan_secrets.sh' 2>/dev/null; then
  printf '%s\n' "${RED}FAIL: credential-in-URL (user:pass@host) detected above.${RESET}"
  status=1
fi

if [ "${status}" -eq 0 ]; then
  printf '%s\n' "${GREEN}OK: no new secrets detected.${RESET}"
fi
exit "${status}"
