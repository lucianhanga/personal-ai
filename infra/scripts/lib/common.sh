#!/usr/bin/env bash
#
# common.sh - Shared helpers for the A100 GPU dev VM scripts. SOURCE this file;
# it is not meant to be executed directly.
#
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "${SCRIPT_DIR}/lib/common.sh"
#
# Design: host resolution here is AZURE-NATIVE and terraform-free. The project's
# resource names are deterministic (source of truth: infra/terraform/main.tf):
#
#   resource group   ai-<instance>-a100-rg
#   virtual machine   vm-ai-a100-<instance>
#   public IP         vm-ai-a100-<instance>-ip
#
# so any instance can be found from its name via `az` alone, even in a fresh
# checkout where Terraform has never been initialized. This is what keeps
# connect/tunnel/stop/start/upload working when there is no local Terraform
# state (the failure mode that made them exit silently before).
#
# Everything here is bash 3.2 safe (macOS default shell) and assumes the caller
# has already set `set -euo pipefail`. It does NOT set shell options itself.

# Guard against double-sourcing.
[[ -n "${_INFRA_COMMON_SOURCED:-}" ]] && return 0
_INFRA_COMMON_SOURCED=1

# --- Colors / logging (TTY-guarded) ----------------------------------------
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

# --- Project conventions ---------------------------------------------------
ADMIN_USER_DEFAULT="azureuser"
DEFAULT_KEY="${HOME}/.ssh/ai-a100-devel"

# One canonical SSH option set: bounded connect timeout + TOFU host keys.
SSH_BASE_OPTS=(-o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new)

# --- Deterministic resource names (mirror infra/terraform/main.tf) ----------
rg_name() { printf 'ai-%s-a100-rg' "$1"; }
vm_name() { printf 'vm-ai-a100-%s' "$1"; }
ip_name() { printf 'vm-ai-a100-%s-ip' "$1"; }

# --- Subscription option ----------------------------------------------------
# Scripts set SUBSCRIPTION (from -s/--subscription) before calling helpers; this
# rebuilds the SUB_OPT array that is appended to every az call. Guarded for bash
# 3.2 + set -u via the ${SUB_OPT[@]+"${SUB_OPT[@]}"} idiom at each use site.
SUB_OPT=()
common_init_sub() {
  SUB_OPT=()
  # Note: an "[[ ... ]] && ..." one-liner here would return non-zero when
  # SUBSCRIPTION is empty and, as the function's last command, abort the caller
  # under set -e. Use a full if so the function always returns 0.
  if [[ -n "${SUBSCRIPTION:-}" ]]; then
    SUB_OPT=(--subscription "$SUBSCRIPTION")
  fi
}

# Read the pinned subscription_id from terraform.tfvars, the same source the
# Terraform provider uses. Echoes the id (or nothing). Lets az calls target the
# exact subscription a deployment lands in, instead of the az CLI default.
# Usage: SUB="$(tfvars_subscription "$TF_DIR")"
tfvars_subscription() {
  local tfvars="${1}/terraform.tfvars"
  [[ -f "$tfvars" ]] || return 0
  grep -E '^[[:space:]]*subscription_id[[:space:]]*=' "$tfvars" 2>/dev/null \
    | head -n1 \
    | sed -E 's/^[^=]*=[[:space:]]*"?([^"#[:space:]]+)"?.*/\1/'
}

# --- Prerequisite checks ----------------------------------------------------
require_tools() {
  local t missing=0
  for t in "$@"; do
    command -v "$t" >/dev/null 2>&1 || { log_err "Required tool not found: $t"; missing=1; }
  done
  [[ "$missing" -eq 0 ]] || exit 3
}

require_az_login() {
  common_init_sub
  if ! az account show ${SUB_OPT[@]+"${SUB_OPT[@]}"} >/dev/null 2>&1; then
    log_err "Not logged in to Azure (or subscription not accessible). Run: az login"
    exit 4
  fi
}

# --- Azure-native instance resolution --------------------------------------
# resolve_instance <instance> -> sets globals RG, VM, IP_RES, PUBIP, ADMIN.
# Terraform-free; uses the deterministic names + an RG-scoped public-IP lookup.
# Returns 5 (and logs) if the public IP cannot be read, which under the caller's
# set -e aborts with a clear message instead of failing silently later.
resolve_instance() {
  local inst="$1"
  RG="$(rg_name "$inst")"
  VM="$(vm_name "$inst")"
  IP_RES="$(ip_name "$inst")"
  ADMIN="$ADMIN_USER_DEFAULT"
  PUBIP="$(az network public-ip show -g "$RG" -n "$IP_RES" \
            --query ipAddress -o tsv ${SUB_OPT[@]+"${SUB_OPT[@]}"} 2>/dev/null || echo "")"
  if [[ -z "$PUBIP" || "$PUBIP" == "None" ]]; then
    log_err "Could not resolve a public IP for instance '${inst}' (looked for ${IP_RES} in ${RG})."
    log_err "It may not be provisioned, may live in a different subscription, or its IP is unassigned."
    log_err "Provision it with: scripts/provision.sh --name ${inst}"
    return 5
  fi
  return 0
}

# Resolve only RG + VM names (no Azure call). Enough for power/deallocate/start
# operations that do not need the public IP.
resolve_names() {
  local inst="$1"
  RG="$(rg_name "$inst")"
  VM="$(vm_name "$inst")"
}

# vm_exists <rg> <vm> -> 0 if the VM is present in Azure, non-zero otherwise.
vm_exists() {
  az vm show --resource-group "$1" --name "$2" \
    --query id -o tsv ${SUB_OPT[@]+"${SUB_OPT[@]}"} >/dev/null 2>&1
}

# --- VM power state ---------------------------------------------------------
# vm_power_state <rg> <vm> -> echoes running|deallocated|stopped|...|unknown.
vm_power_state() {
  az vm get-instance-view --resource-group "$1" --name "$2" \
    --query "instanceView.statuses[?starts_with(code,'PowerState/')].code | [0]" \
    -o tsv ${SUB_OPT[@]+"${SUB_OPT[@]}"} 2>/dev/null | sed 's#PowerState/##' || echo "unknown"
}
