#!/usr/bin/env bash
#
# destroy.sh - Permanently destroy an A100 dev VM instance and ALL its resources
# (runs 'terraform destroy' for that instance's workspace). Deletes the VM, OS
# disk, network, public IP and resource group. ALL DATA IS LOST. Irreversible.
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for a in "$@"; do
  case "$a" in
    -h|--help)
      cat <<EOF
Usage: $(basename "$0") [-n|--name <name>] [-y|--auto-approve]

Permanently destroy the instance and ALL its resources (terraform destroy):
the VM, OS disk, network, public IP and resource group. ALL DATA IS LOST.
This is irreversible. Default name: devel.

  -n, --name <name>   Instance to destroy (alias: --instance). Default: devel.
  -y, --auto-approve  Skip the confirmation prompt.

To only stop billing while keeping the machine and data, use stop.sh instead.
EOF
      exit 0 ;;
  esac
done

exec "${SCRIPT_DIR}/deprovision.sh" --destroy "$@"
