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

# --- Shared helpers --------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

# --- Defaults --------------------------------------------------------------
INSTANCE="devel"   # instance to tunnel to.
IDENTITY=""
SUBSCRIPTION=""    # optional az subscription (id or name); empty = CLI default.
SPECS=()   # raw port specs to translate into -L arguments

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Open SSH local port forwarding to the A100 GPU dev VM. The tunnel stays in the
foreground; press Ctrl-C to close it.

Options:
  -L, --local <spec>      Forward a port. Repeatable. Formats:
                            PORT | LPORT:RPORT | LPORT:RHOST:RPORT
      --ui                Preset: forward 5173 (Vite dev UI).
      --api               Preset: forward 8765 (personalAI backend).
      --jupyter           Preset: forward 8888 (Jupyter).
      --tensorboard       Preset: forward 6006 (TensorBoard).
      --ollama            Preset: forward 11434 (Ollama API).
      --dev               Preset bundle: --ui + --api (UI 5173 + backend 8765).
  -n, --name <name>       Instance to tunnel to (alias: --instance). Default: devel.
  -i, --identity <path>   Private key to authenticate with (ssh -i).
  -s, --subscription <id|name>  Azure subscription to resolve the VM in. Default: CLI default.
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
    --api)         add_spec "8765"; shift ;;
    --jupyter)     add_spec "8888"; shift ;;
    --tensorboard) add_spec "6006"; shift ;;
    --ollama)      add_spec "11434"; shift ;;
    --dev)         add_spec "5173"; add_spec "8765"; shift ;;
    -n|--name|--instance) INSTANCE="${2:-}"; shift 2 ;;
    -i|--identity) IDENTITY="${2:-}"; shift 2 ;;
    -s|--subscription) SUBSCRIPTION="${2:-}"; shift 2 ;;
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

# --- Prerequisites & resolution --------------------------------------------
require_tools az ssh
require_az_login
resolve_instance "$INSTANCE"

# --- Check power state ------------------------------------------------------
POWER="$(vm_power_state "$RG" "$VM")"
if [[ "$POWER" != "running" ]]; then
  log_warn "VM power state is '${POWER}'. Start it first: scripts/start.sh --name ${INSTANCE}"
  [[ "$POWER" == "deallocated" || "$POWER" == "stopped" ]] && exit 6
fi

# --- Build and run the tunnel ----------------------------------------------
[[ -z "$IDENTITY" && -f "$DEFAULT_KEY" ]] && IDENTITY="$DEFAULT_KEY"
SSH_CMD=(ssh -N "${SSH_BASE_OPTS[@]}"
         -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes)
[[ -n "$IDENTITY" ]] && SSH_CMD+=(-i "$IDENTITY")
SSH_CMD+=("${FORWARDS[@]}" "${ADMIN}@${PUBIP}")

log_ok "Opening tunnel to ${ADMIN}@${PUBIP}:"
for f in "${FRIENDLY[@]}"; do
  log_info "  ${f}"
done
log_warn "Tunnel is open. Press Ctrl-C to close it."
exec "${SSH_CMD[@]}"
