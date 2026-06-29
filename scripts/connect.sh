#!/usr/bin/env bash
#
# connect.sh - Open an SSH session to the A100 GPU dev VM.
#
# Reads the public IP and admin username from Terraform outputs, checks the VM
# power state, and SSHes in. Any extra arguments after "--" (or a single
# trailing command) are run on the VM instead of an interactive shell.
#
# Examples:
#   scripts/connect.sh                 # interactive shell
#   scripts/connect.sh nvidia-smi      # run one command and exit
#   scripts/connect.sh -i ~/.ssh/mykey # use a specific private key
#   scripts/connect.sh -- -L 8888:localhost:8888   # forward a port (Jupyter)
#
set -euo pipefail

# --- Colors ----------------------------------------------------------------
if [[ -t 1 ]]; then
  GREEN='\033[0;32m'
  RED='\033[0;31m'
  YELLOW='\033[0;33m'
  NC='\033[0m'
else
  GREEN=''; RED=''; YELLOW=''; NC=''
fi

log_ok()   { printf "${GREEN}[ OK ]${NC} %s\n" "$*"; }
log_warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$*"; }
log_err()  { printf "${RED}[FAIL]${NC} %s\n" "$*" >&2; }

# --- Paths -----------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$(cd "${SCRIPT_DIR}/../terraform" && pwd)"

# --- Defaults --------------------------------------------------------------
IDENTITY=""
SSH_EXTRA_ARGS=()
REMOTE_CMD=()

usage() {
  cat <<EOF
Usage: $(basename "$0") [options] [-- <ssh-args...>] [remote-command...]

Open an SSH session to the A100 GPU dev VM.

Options:
  -i, --identity <path>   Private key to authenticate with (ssh -i).
  -h, --help              Show this help.

Anything after "--" is passed straight to ssh (e.g. -L for port forwarding).
A trailing command (e.g. "nvidia-smi") is executed on the VM and then exits.
EOF
}

# --- Parse args ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -i|--identity) IDENTITY="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --) shift; SSH_EXTRA_ARGS+=("$@"); break ;;
    *) REMOTE_CMD+=("$1"); shift ;;
  esac
done

# --- Prerequisites ---------------------------------------------------------
for tool in az terraform ssh; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    log_err "Required tool not found: $tool"; exit 3
  fi
done
if ! az account show >/dev/null 2>&1; then
  log_err "Not logged in to Azure. Run: az login"; exit 4
fi

# --- Resolve targets from Terraform outputs --------------------------------
cd "$TF_DIR"
ADMIN="$(terraform output -raw admin_username 2>/dev/null || echo "azureuser")"
PUBIP="$(terraform output -raw public_ip_address 2>/dev/null || echo "")"
RG="$(terraform output -raw resource_group_name 2>/dev/null || echo "")"
VM="$(terraform output -raw vm_name 2>/dev/null || echo "")"

if [[ -z "$PUBIP" || -z "$RG" || -z "$VM" ]]; then
  log_err "Could not read Terraform outputs. Has the environment been provisioned?"
  log_err "Run: scripts/provision.sh"
  exit 5
fi

# --- Check power state ------------------------------------------------------
POWER="$(az vm get-instance-view --resource-group "$RG" --name "$VM" \
         --query "instanceView.statuses[?starts_with(code,'PowerState/')].code | [0]" \
         -o tsv 2>/dev/null | sed 's#PowerState/##' || echo "unknown")"

case "$POWER" in
  running)
    log_ok "VM is running."
    ;;
  deallocated)
    log_warn "VM is deallocated. Start it first: scripts/start.sh"
    exit 6
    ;;
  stopped)
    log_warn "VM is stopped. Start it first: scripts/start.sh"
    exit 6
    ;;
  *)
    log_warn "VM power state is '${POWER}'. Attempting to connect anyway."
    ;;
esac

# --- Build and run SSH command ---------------------------------------------
SSH_CMD=(ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
[[ -n "$IDENTITY" ]] && SSH_CMD+=(-i "$IDENTITY")
[[ ${#SSH_EXTRA_ARGS[@]} -gt 0 ]] && SSH_CMD+=("${SSH_EXTRA_ARGS[@]}")
SSH_CMD+=("${ADMIN}@${PUBIP}")
[[ ${#REMOTE_CMD[@]} -gt 0 ]] && SSH_CMD+=("${REMOTE_CMD[@]}")

log_ok "Connecting to ${ADMIN}@${PUBIP} ..."
exec "${SSH_CMD[@]}"
