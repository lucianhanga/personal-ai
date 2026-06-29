#!/usr/bin/env bash
#
# tunnel.sh - SSH local port forwarding to the A100 GPU dev VM.
#
# Makes a service running on the remote VM reachable on your local machine via
# 'localhost'. Uses SSH local forwarding (ssh -L). The tunnel stays open in the
# foreground; press Ctrl-C to close it.
#
# Port spec formats accepted by -L/--local:
#   PORT                 -> localhost:PORT  forwards to  remote localhost:PORT
#   LPORT:RPORT          -> localhost:LPORT forwards to  remote localhost:RPORT
#   LPORT:RHOST:RPORT    -> localhost:LPORT forwards to  remote RHOST:RPORT
#
# Presets (add common AI-dev services; combine freely):
#   --jupyter            8888  (Jupyter / JupyterLab)
#   --tensorboard        6006  (TensorBoard)
#   --ollama             11434 (Ollama API)
#
# Examples:
#   scripts/tunnel.sh --jupyter
#   scripts/tunnel.sh -L 8888 -L 6006
#   scripts/tunnel.sh -L 9000:8000           # local 9000 -> remote 8000
#   scripts/tunnel.sh --jupyter --tensorboard --ollama
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
log_info() { printf "%s\n" "$*"; }

# --- Paths -----------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$(cd "${SCRIPT_DIR}/../terraform" && pwd)"

# --- Defaults --------------------------------------------------------------
INSTANCE="devel"   # instance to tunnel to; selects its Terraform workspace.
IDENTITY=""
# Default to the dedicated project key (created by provision.sh) if present;
# an explicit -i/--identity overrides it.
DEFAULT_KEY="${HOME}/.ssh/ai-a100-devel"
SPECS=()   # raw port specs to translate into -L arguments

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Open SSH local port forwarding to the A100 GPU dev VM. The tunnel stays in the
foreground; press Ctrl-C to close it.

Options:
  -L, --local <spec>      Forward a port. Repeatable. Formats:
                            PORT | LPORT:RPORT | LPORT:RHOST:RPORT
      --ui                Preset: forward 5173 (Vite dev UI - doktokNG / personalAI).
      --api               Preset: forward backend APIs - 8000 (doktokNG) and
                          8765 (personalAI loopback backend).
      --jupyter           Preset: forward 8888 (Jupyter).
      --tensorboard       Preset: forward 6006 (TensorBoard).
      --ollama            Preset: forward 11434 (Ollama API).
      --dev               Preset bundle: --ui + --api (UI 5173 + backends 8000 & 8765).
  -n, --name <name>       Instance to tunnel to (alias: --instance). Default: devel.
  -i, --identity <path>   Private key to authenticate with (ssh -i).
  -h, --help              Show this help.

Everything is forwarded to the VM's localhost over the SSH tunnel, so the
services are reachable only from your machine and are never exposed to the
internet (the firewall opens port 22 only). At least one port is required.

Examples:
  $(basename "$0") --name train --dev          # UI + API + Ollama in one go
  $(basename "$0") --name train --ui           # just the web UI on localhost:5173
EOF
}

add_spec() { SPECS+=("$1"); }

# --- Parse args ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -L|--local)    add_spec "${2:-}"; shift 2 ;;
    --ui)          add_spec "5173"; shift ;;
    --api)         add_spec "8000"; add_spec "8765"; shift ;;
    --jupyter)     add_spec "8888"; shift ;;
    --tensorboard) add_spec "6006"; shift ;;
    --ollama)      add_spec "11434"; shift ;;
    --dev)         add_spec "5173"; add_spec "8000"; add_spec "8765"; shift ;;
    -n|--name|--instance) INSTANCE="${2:-}"; shift 2 ;;
    -i|--identity) IDENTITY="${2:-}"; shift 2 ;;
    -h|--help)     usage; exit 0 ;;
    *) log_err "Unknown argument: $1"; usage; exit 2 ;;
  esac
done

[[ -z "$INSTANCE" ]] && { log_err "--name requires a non-empty value."; exit 2; }

if [[ ${#SPECS[@]} -eq 0 ]]; then
  log_err "No ports to forward. Use -L <spec> or a preset (--jupyter, etc.)."
  usage; exit 2
fi

# --- Translate specs into ssh -L arguments ---------------------------------
# PORT -> PORT:localhost:PORT ; LPORT:RPORT -> LPORT:localhost:RPORT ;
# LPORT:RHOST:RPORT -> passed through unchanged.
FORWARDS=()
FRIENDLY=()
for spec in "${SPECS[@]}"; do
  case "$spec" in
    *:*:*)
      FORWARDS+=("-L" "$spec")
      FRIENDLY+=("localhost:${spec%%:*} -> remote ${spec#*:}")
      ;;
    *:*)
      lport="${spec%%:*}"; rport="${spec##*:}"
      FORWARDS+=("-L" "${lport}:localhost:${rport}")
      FRIENDLY+=("localhost:${lport} -> remote localhost:${rport}")
      ;;
    *)
      if ! [[ "$spec" =~ ^[0-9]+$ ]]; then
        log_err "Invalid port spec: '$spec'"; exit 2
      fi
      FORWARDS+=("-L" "${spec}:localhost:${spec}")
      FRIENDLY+=("localhost:${spec} -> remote localhost:${spec}")
      ;;
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
# Per-instance state: select (or create) the workspace for this instance first.
cd "$TF_DIR"
terraform workspace select "$INSTANCE" 2>/dev/null || terraform workspace new "$INSTANCE" >/dev/null 2>&1
ADMIN="$(terraform output -raw admin_username 2>/dev/null || echo "azureuser")"
PUBIP="$(terraform output -raw public_ip_address 2>/dev/null || echo "")"
RG="$(terraform output -raw resource_group_name 2>/dev/null || echo "")"
VM="$(terraform output -raw vm_name 2>/dev/null || echo "")"

if [[ -z "$PUBIP" || -z "$RG" || -z "$VM" ]]; then
  log_err "Could not read Terraform outputs for instance '${INSTANCE}'. Has it been provisioned?"
  log_err "Run: scripts/provision.sh --name ${INSTANCE}"
  exit 5
fi

# --- Check power state ------------------------------------------------------
POWER="$(az vm get-instance-view --resource-group "$RG" --name "$VM" \
         --query "instanceView.statuses[?starts_with(code,'PowerState/')].code | [0]" \
         -o tsv 2>/dev/null | sed 's#PowerState/##' || echo "unknown")"

if [[ "$POWER" != "running" ]]; then
  log_warn "VM power state is '${POWER}'. Start it first: scripts/start.sh"
  [[ "$POWER" == "deallocated" || "$POWER" == "stopped" ]] && exit 6
fi

# --- Build and run the tunnel ----------------------------------------------
[[ -z "$IDENTITY" && -f "$DEFAULT_KEY" ]] && IDENTITY="$DEFAULT_KEY"
SSH_CMD=(ssh -N -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new
         -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes)
[[ -n "$IDENTITY" ]] && SSH_CMD+=(-i "$IDENTITY")
SSH_CMD+=("${FORWARDS[@]}" "${ADMIN}@${PUBIP}")

log_ok "Opening tunnel to ${ADMIN}@${PUBIP}:"
for f in "${FRIENDLY[@]}"; do
  log_info "  ${f}"
done
log_warn "Tunnel is open. Press Ctrl-C to close it."
exec "${SSH_CMD[@]}"
