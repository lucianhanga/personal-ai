#!/usr/bin/env bash
#
# monitor.sh - Read-only status dashboard for the A100 GPU dev VM.
#
# Shows:
#   - VM power state and provisioning state
#   - Running / deallocated / evicted (Spot) status
#   - Public IP and SSH reachability (port 22)
#   - Size/SKU and location
#   - Optional GPU check (nvidia-smi over SSH) with --gpu
#   - Spot cost reminder
#
# This script performs NO changes. It only reads state.
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

c_ok()   { printf "${GREEN}%s${NC}" "$*"; }
c_warn() { printf "${YELLOW}%s${NC}" "$*"; }
c_err()  { printf "${RED}%s${NC}" "$*"; }

log_err()  { printf "${RED}[FAIL]${NC} %s\n" "$*" >&2; }

# --- Paths -----------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$(cd "${SCRIPT_DIR}/../terraform" && pwd)"

# --- Defaults --------------------------------------------------------------
DO_GPU="false"
WATCH_INTERVAL=""

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Read-only status dashboard for the A100 GPU dev VM.

Options:
      --gpu             SSH into the VM (if reachable) and run nvidia-smi.
      --watch <secs>    Refresh continuously every <secs> seconds.
  -h, --help            Show this help.
EOF
}

# --- Parse args ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --gpu) DO_GPU="true"; shift ;;
    --watch) WATCH_INTERVAL="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) log_err "Unknown argument: $1"; usage; exit 2 ;;
  esac
done

# --- Prerequisites ---------------------------------------------------------
check_prereqs() {
  for tool in az terraform; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      log_err "Required tool not found: $tool"; exit 3
    fi
  done
  if ! az account show >/dev/null 2>&1; then
    log_err "Not logged in to Azure. Run: az login"; exit 4
  fi
}

# --- Resolve targets from Terraform outputs --------------------------------
resolve_targets() {
  cd "$TF_DIR"
  RG="$(terraform output -raw resource_group_name 2>/dev/null || echo "")"
  VM="$(terraform output -raw vm_name 2>/dev/null || echo "")"
  ADMIN="$(terraform output -raw admin_username 2>/dev/null || echo "azureuser")"
  PUBIP="$(terraform output -raw public_ip_address 2>/dev/null || echo "")"
  if [[ -z "$RG" || -z "$VM" ]]; then
    log_err "Could not read Terraform outputs. Has the environment been provisioned?"
    exit 5
  fi
}

# --- SSH reachability ------------------------------------------------------
check_ssh() {
  local ip="$1"
  [[ -z "$ip" ]] && return 1
  if command -v nc >/dev/null 2>&1; then
    nc -z -w 5 "$ip" 22 >/dev/null 2>&1
  else
    # Fallback using bash /dev/tcp with a timeout.
    timeout 5 bash -c "cat < /dev/null > /dev/tcp/${ip}/22" >/dev/null 2>&1
  fi
}

dashboard() {
  resolve_targets

  # Instance view -> power and provisioning state.
  local iv power prov
  iv="$(az vm get-instance-view --resource-group "$RG" --name "$VM" \
        --query "instanceView.statuses[].code" -o tsv 2>/dev/null || echo "")"
  power="$(echo "$iv" | grep '^PowerState/' | sed 's#PowerState/##' || true)"
  prov="$(echo "$iv" | grep '^ProvisioningState/' | sed 's#ProvisioningState/##' || true)"
  [[ -z "$power" ]] && power="unknown"
  [[ -z "$prov" ]] && prov="unknown"

  local size location
  size="$(az vm show --resource-group "$RG" --name "$VM" \
          --query "hardwareProfile.vmSize" -o tsv 2>/dev/null || echo "unknown")"
  location="$(az vm show --resource-group "$RG" --name "$VM" \
          --query "location" -o tsv 2>/dev/null || echo "unknown")"

  echo "==============================================================="
  echo " A100 GPU dev VM status   ($(date '+%Y-%m-%d %H:%M:%S'))"
  echo "==============================================================="
  printf " Resource group : %s\n" "$RG"
  printf " VM name        : %s\n" "$VM"
  printf " Size / SKU     : %s\n" "$size"
  printf " Location       : %s\n" "$location"
  printf " Public IP      : %s\n" "${PUBIP:-none}"

  printf " Power state    : "
  case "$power" in
    running)     c_ok "running"; echo ;;
    deallocated) c_warn "deallocated (GPU billing stopped)"; echo ;;
    stopped)     c_warn "stopped (still allocated - may incur charges)"; echo ;;
    *)           c_err "$power"; echo ;;
  esac

  printf " Provisioning   : "
  case "$prov" in
    succeeded) c_ok "succeeded"; echo ;;
    failed)    c_err "failed (possible Spot eviction)"; echo ;;
    *)         c_warn "$prov"; echo ;;
  esac

  # SSH reachability.
  printf " SSH (port 22)  : "
  if [[ "$power" == "running" ]]; then
    if check_ssh "$PUBIP"; then
      c_ok "reachable"; echo
    else
      c_warn "not reachable (booting, NSG source restriction, or firewall)"; echo
    fi
  else
    c_warn "skipped (VM not running)"; echo
  fi

  # Optional GPU check.
  if [[ "$DO_GPU" == "true" ]]; then
    echo "---------------------------------------------------------------"
    if [[ "$power" == "running" ]] && check_ssh "$PUBIP"; then
      echo " GPU (nvidia-smi):"
      if ! ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
            "${ADMIN}@${PUBIP}" "nvidia-smi" 2>/dev/null; then
        c_warn " Could not run nvidia-smi (SSH key not loaded, or driver not ready)."; echo
      fi
    else
      c_warn " GPU check skipped (VM not running or not reachable)."; echo
    fi
  fi

  echo "---------------------------------------------------------------"
  c_warn " Spot VM: pricing varies and Azure may evict on capacity demand."; echo
  echo "         Deallocate when idle: scripts/deprovision.sh --deallocate"
  echo "==============================================================="
}

main() {
  check_prereqs
  if [[ -n "$WATCH_INTERVAL" ]]; then
    if ! [[ "$WATCH_INTERVAL" =~ ^[0-9]+$ ]] || [[ "$WATCH_INTERVAL" -lt 1 ]]; then
      log_err "--watch requires a positive integer number of seconds."
      exit 2
    fi
    while true; do
      clear
      dashboard
      sleep "$WATCH_INTERVAL"
    done
  else
    dashboard
  fi
}

main "$@"
