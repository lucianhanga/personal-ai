#!/usr/bin/env bash
# Prove the cosign signing toolchain works: sign + verify a test artifact with an
# ephemeral key, fully offline (no Fulcio/Rekor). Real releases use keyless signing
# (see docs/development/releasing.md). Requires `cosign` on PATH.
set -euo pipefail

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; RESET=$'\033[0m'

if ! command -v cosign >/dev/null 2>&1; then
  printf '%s\n' "${RED}FAIL: cosign not found on PATH.${RESET}"
  exit 1
fi

workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT
cd "${workdir}"

export COSIGN_PASSWORD=""
echo "personalai signing smoke $(date -u +%s)" > artifact.txt

cosign generate-key-pair >/dev/null
cosign sign-blob --key cosign.key --yes --tlog-upload=false \
  --output-signature artifact.sig artifact.txt >/dev/null
cosign verify-blob --key cosign.pub --insecure-ignore-tlog=true \
  --signature artifact.sig artifact.txt >/dev/null

printf '%s\n' "${GREEN}OK: signed and verified a test artifact with cosign.${RESET}"
