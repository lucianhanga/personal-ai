#!/usr/bin/env bash
#
# start.sh - Start a previously stopped (deallocated) A100 GPU dev VM.
#
# Thin wrapper around 'deprovision.sh --start'. As a Spot VM, start can fail if
# there is no spot capacity in the region right now. Any extra arguments are
# passed through.
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/deprovision.sh" --start "$@"
