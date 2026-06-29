#!/usr/bin/env bash
#
# connect.sh - Open an SSH session to the A100 GPU dev VM.
#
# Resolves the VM's public IP from Azure (deterministic resource names, no
# Terraform state required), checks the VM power state, and SSHes in. Any extra
# arguments after "--" (or a single trailing command) are run on the VM instead
# of an interactive shell.
#
# Examples:
#   scripts/connect.sh                 # interactive shell (instance: devel)
#   scripts/connect.sh -n train        # connect to another instance
#   scripts/connect.sh nvidia-smi      # run one command and exit
#   scripts/connect.sh -i ~/.ssh/mykey # use a specific private key
#   scripts/connect.sh -- -L 8888:localhost:8888   # forward a port (Jupyter)
#
set -euo pipefail

# --- Shared helpers --------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

# --- Defaults --------------------------------------------------------------
INSTANCE="devel"   # instance to connect to.
IDENTITY=""
SUBSCRIPTION=""    # optional az subscription (id or name); empty = CLI default.
SSH_EXTRA_ARGS=()
REMOTE_CMD=()

usage() {
  cat <<EOF
Usage: $(basename "$0") [options] [-- <ssh-args...>] [remote-command...]

Open an SSH session to the A100 GPU dev VM.

Options:
  -n, --name <name>            Instance to connect to (alias: --instance). Default: devel.
  -i, --identity <path>        Private key to authenticate with (ssh -i).
  -s, --subscription <id|name> Azure subscription to resolve the VM in. Default: CLI default.
  -h, --help                   Show this help.

Anything after "--" is passed straight to ssh (e.g. -L for port forwarding).
A trailing command (e.g. "nvidia-smi") is executed on the VM and then exits.
EOF
}

# --- Parse args ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--name|--instance) INSTANCE="${2:-}"; shift 2 ;;
    -i|--identity) IDENTITY="${2:-}"; shift 2 ;;
    -s|--subscription) SUBSCRIPTION="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --) shift; SSH_EXTRA_ARGS+=("$@"); break ;;
    *) REMOTE_CMD+=("$1"); shift ;;
  esac
done

[[ -z "$INSTANCE" ]] && { log_err "--name requires a non-empty value."; exit 2; }

# --- Prerequisites & resolution --------------------------------------------
require_tools az ssh
require_az_login
resolve_instance "$INSTANCE"

# --- Check power state ------------------------------------------------------
POWER="$(vm_power_state "$RG" "$VM")"
case "$POWER" in
  running)
    log_ok "VM is running."
    ;;
  deallocated|stopped)
    log_warn "VM is ${POWER}. Start it first: scripts/start.sh --name ${INSTANCE}"
    exit 6
    ;;
  *)
    log_warn "VM power state is '${POWER}'. Attempting to connect anyway."
    ;;
esac

# --- Build and run SSH command ---------------------------------------------
[[ -z "$IDENTITY" && -f "$DEFAULT_KEY" ]] && IDENTITY="$DEFAULT_KEY"
SSH_CMD=(ssh "${SSH_BASE_OPTS[@]}")
[[ -n "$IDENTITY" ]] && SSH_CMD+=(-i "$IDENTITY")
[[ ${#SSH_EXTRA_ARGS[@]} -gt 0 ]] && SSH_CMD+=("${SSH_EXTRA_ARGS[@]}")
SSH_CMD+=("${ADMIN}@${PUBIP}")
[[ ${#REMOTE_CMD[@]} -gt 0 ]] && SSH_CMD+=("${REMOTE_CMD[@]}")

log_ok "Connecting to ${ADMIN}@${PUBIP} ..."
exec "${SSH_CMD[@]}"
