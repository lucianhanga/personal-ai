#!/usr/bin/env bash
#
# stop.sh - Stop an A100 dev VM instance. "Stop" always DEALLOCATES it: powers
# the VM off AND releases the GPU so compute billing stops ($0 while off). The
# disk, public IP, network, and data are kept; resume with start.sh. There is
# deliberately no plain "stop" that would keep the VM allocated and still billing.
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for a in "$@"; do
  case "$a" in
    -h|--help)
      cat <<EOF
Usage: $(basename "$0") [-n|--name <name>] [-y|--auto-approve]

Stop (deallocate) the instance: powers it off and halts GPU compute billing,
keeping the disk, IP, network, and data. Resume with start.sh. Default name: devel.

  -n, --name <name>   Instance to stop (alias: --instance). Default: devel.
  -y, --auto-approve  Skip confirmation prompts.

You still pay for the Premium OS disk and the Standard static public IP while
stopped. To remove all charges and data, use destroy.sh.
EOF
      exit 0 ;;
  esac
done

exec "${SCRIPT_DIR}/deprovision.sh" --deallocate "$@"
