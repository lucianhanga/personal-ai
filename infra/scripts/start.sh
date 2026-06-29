#!/usr/bin/env bash
#
# start.sh - Start a previously stopped (deallocated) A100 dev VM instance.
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for a in "$@"; do
  case "$a" in
    -h|--help)
      cat <<EOF
Usage: $(basename "$0") [-n|--name <name>] [-y|--auto-approve]

Start a previously stopped (deallocated) instance. Default name: devel.

  -n, --name <name>   Instance to start (alias: --instance). Default: devel.
  -y, --auto-approve  Skip confirmation prompts.

Note: as a Spot VM, start can fail if there is no spot capacity right now.
EOF
      exit 0 ;;
  esac
done

exec "${SCRIPT_DIR}/deprovision.sh" --start "$@"
