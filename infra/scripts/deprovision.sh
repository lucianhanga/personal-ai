#!/usr/bin/env bash
#
# deprovision.sh - Cost control for the A100 GPU dev VM.
#
# Modes:
#   --deallocate (default)  Stop the VM and stop COMPUTE (GPU) billing while
#                           keeping the OS disk, public IP, network, and
#                           Terraform state intact. Resume quickly with --start.
#   --start                 Start a previously deallocated VM.
#   --destroy               Full 'terraform destroy'. DELETES the OS disk and
#                           ALL data on it. Irreversible.
#
# Cost note:
#   deallocate -> you stop paying for the GPU compute, but you STILL pay for the
#                 Premium OS disk and the Standard static public IP.
#   destroy    -> removes everything (no further charges, no data).
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
MODE="deallocate"
AUTO_APPROVE="false"
INSTANCE="devel"   # instance name; selects the Terraform workspace + targets.

usage() {
  cat <<EOF
Usage: $(basename "$0") [mode] [options]

Modes (choose one):
  --deallocate    (default) Stop the VM and stop GPU compute billing. Keeps the
                  disk, IP, network, and Terraform state. Resume with --start.
  --start         Start a previously deallocated VM.
  --destroy       Run 'terraform destroy'. DELETES the OS disk and ALL data.

Options:
  -n, --name <name>    Instance to act on (alias: --instance). Default: devel.
                       Selects that instance's Terraform workspace, so only that
                       instance is deallocated / started / destroyed.
  -y, --auto-approve   Skip confirmation prompts.
  -h, --help           Show this help.

Cost guidance:
  deallocate  -> stops GPU/compute charges; you still pay for the Premium disk
                 and the Standard static public IP.
  destroy     -> removes all resources and stops all charges; data is lost.
EOF
}

# --- Parse args ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --deallocate) MODE="deallocate"; shift ;;
    --start)      MODE="start"; shift ;;
    --destroy)    MODE="destroy"; shift ;;
    -n|--name|--instance) INSTANCE="${2:-}"; shift 2 ;;
    -y|--auto-approve) AUTO_APPROVE="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) log_err "Unknown argument: $1"; usage; exit 2 ;;
  esac
done

[[ -z "$INSTANCE" ]] && { log_err "--name requires a non-empty value."; exit 2; }

# Per-instance state: select (or create) the workspace named after the instance
# before any terraform output/destroy. Requires terraform to be initialized.
select_workspace() {
  terraform -chdir="$TF_DIR" workspace select "$INSTANCE" 2>/dev/null \
    || terraform -chdir="$TF_DIR" workspace new "$INSTANCE" >/dev/null 2>&1
}

# --- Prerequisite checks ---------------------------------------------------
check_prereqs() {
  local need_tf="$1"
  if ! command -v az >/dev/null 2>&1; then
    log_err "Required tool not found: az"; exit 3
  fi
  if [[ "$need_tf" == "true" ]] && ! command -v terraform >/dev/null 2>&1; then
    log_err "Required tool not found: terraform"; exit 3
  fi
  if ! az account show >/dev/null 2>&1; then
    log_err "Not logged in to Azure. Run: az login"; exit 4
  fi
}

# --- Resolve RG and VM name from Terraform state ---------------------------
resolve_targets() {
  cd "$TF_DIR"
  select_workspace
  RG="$(terraform output -raw resource_group_name 2>/dev/null || echo "")"
  VM="$(terraform output -raw vm_name 2>/dev/null || echo "")"
  if [[ -z "$RG" || -z "$VM" ]]; then
    log_err "Could not read resource group / VM name for instance '${INSTANCE}' from Terraform outputs."
    log_err "Has this instance been provisioned? Run: scripts/provision.sh --name ${INSTANCE}"
    exit 5
  fi
}

confirm() {
  local prompt="$1"
  if [[ "$AUTO_APPROVE" == "true" ]]; then return 0; fi
  printf "${YELLOW}%s [y/N]: ${NC}" "$prompt"
  read -r reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

do_deallocate() {
  check_prereqs "true"
  resolve_targets
  log_info "Target: VM '${VM}' in resource group '${RG}'."
  if ! confirm "Deallocate the VM (stops GPU billing, keeps disk and IP)?"; then
    log_warn "Aborted. No changes made."; exit 0
  fi
  log_info "Deallocating..."
  az vm deallocate --resource-group "$RG" --name "$VM" --output none
  log_ok "VM deallocated. GPU compute billing stopped."
  log_warn "You still pay for the Premium OS disk and the static public IP."
  log_info "Resume later with: scripts/deprovision.sh --start"
}

do_start() {
  check_prereqs "true"
  resolve_targets
  log_info "Target: VM '${VM}' in resource group '${RG}'."
  log_info "Starting..."
  # Note: as a Spot VM, start can fail if there is no spot capacity right now.
  if az vm start --resource-group "$RG" --name "$VM" --output none; then
    log_ok "VM started."
  else
    log_err "Start failed. For a Spot VM this often means no spot capacity is"
    log_err "currently available in the region. Try again later."
    exit 6
  fi
}

do_destroy() {
  check_prereqs "true"
  cd "$TF_DIR"
  select_workspace
  printf "${RED}WARNING: 'terraform destroy' DELETES the OS disk and ALL DATA on instance '${INSTANCE}'.${NC}\n"
  printf "${RED}This is irreversible. The IP, NIC, NSG, VNet and resource group will be removed.${NC}\n"
  if ! confirm "Proceed with full destroy of instance '${INSTANCE}'?"; then
    log_warn "Aborted. Nothing destroyed."; exit 0
  fi
  if [[ "$AUTO_APPROVE" == "true" ]]; then
    terraform destroy -input=false -auto-approve -var "instance=${INSTANCE}"
  else
    terraform destroy -input=false -var "instance=${INSTANCE}"
  fi
  log_ok "Destroy complete. All resources for instance '${INSTANCE}' removed."
}

case "$MODE" in
  deallocate) do_deallocate ;;
  start)      do_start ;;
  destroy)    do_destroy ;;
  *) usage; exit 2 ;;
esac
