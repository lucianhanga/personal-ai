#!/usr/bin/env bash
#
# stop.sh - Stop (deallocate) the A100 GPU dev VM without removing anything.
#
# This is the cost-saving stop: it deallocates the VM so GPU/compute billing
# stops, while keeping the OS disk, public IP, network, and Terraform state so
# you can resume quickly with scripts/start.sh. It does NOT deprovision.
#
# It is a thin wrapper around 'deprovision.sh --deallocate' so there is a single
# implementation. Any extra arguments (e.g. -y) are passed through.
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/deprovision.sh" --deallocate "$@"
