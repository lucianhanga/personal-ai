#!/usr/bin/env bash
#
# deallocate.sh - Deallocate the A100 GPU dev VM (the cost-saving "off").
#
# Deallocating powers the VM off AND releases the physical GPU/CPU/RAM back to
# Azure, so COMPUTE billing stops entirely ($0 while off). The OS disk, public
# IP, network, and Terraform state are kept, so you can resume with
# scripts/start.sh (subject to Spot capacity being available again).
#
# This is intentionally NOT a plain "stop": an Azure VM that is merely stopped
# stays allocated and keeps charging full compute price. We always deallocate.
#
# Thin wrapper around 'deprovision.sh --deallocate' so there is one
# implementation. Extra arguments (e.g. -y) are passed through.
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/deprovision.sh" --deallocate "$@"
