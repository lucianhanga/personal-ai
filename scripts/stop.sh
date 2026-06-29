#!/usr/bin/env bash
#
# stop.sh - Backward-compatible alias. "Stopping" this VM always DEALLOCATES it
# (powers off AND releases the GPU so compute billing stops). There is
# intentionally no plain "stop" that would keep the VM allocated and still
# billing. Forwards to deallocate.sh; extra arguments (e.g. -y) pass through.
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/deallocate.sh" "$@"
