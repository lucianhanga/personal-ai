#!/usr/bin/env bash
# Generate a CycloneDX SBOM of the Python runtime dependencies into sbom/.
# Usage: scripts/generate_sbom.sh   (run via `make sbom`)
set -euo pipefail

GREEN=$'\033[0;32m'; RESET=$'\033[0m'

OUT_DIR="sbom"
REQS="${OUT_DIR}/requirements.txt"
SBOM="${OUT_DIR}/python.cdx.json"

mkdir -p "${OUT_DIR}"

# Locked, runtime-only dependency set (excludes dev tooling).
uv export --no-dev --format requirements-txt --no-emit-workspace > "${REQS}"

# CycloneDX SBOM (reproducible output for stable diffs).
uv run cyclonedx-py requirements "${REQS}" \
  --output-format JSON \
  --output-reproducible \
  --output-file "${SBOM}"

printf '%s\n' "${GREEN}OK: wrote ${SBOM} and ${REQS}.${RESET}"
