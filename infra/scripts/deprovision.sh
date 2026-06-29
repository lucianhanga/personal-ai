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
# deallocate / start resolve the VM directly from Azure (deterministic resource
# names), so they work even when Terraform is not initialized in this checkout.
# Only --destroy needs initialized Terraform state.
#
# Cost note:
#   deallocate -> you stop paying for the GPU compute, but you STILL pay for the
#                 Premium OS disk and the Standard static public IP.
#   destroy    -> removes everything (no further charges, no data).
#
set -euo pipefail

# --- Shared helpers --------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
TF_DIR="$(cd "${SCRIPT_DIR}/../terraform" && pwd)"

# --- Defaults --------------------------------------------------------------
MODE="deallocate"
AUTO_APPROVE="false"
INSTANCE="devel"   # instance name; selects resource names + Terraform workspace.
SUBSCRIPTION=""    # optional az subscription (id or name); empty = CLI default.

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
  -s, --subscription <id|name>  Azure subscription to act in. Default: CLI default.
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
    -s|--subscription) SUBSCRIPTION="${2:-}"; shift 2 ;;
    -y|--auto-approve) AUTO_APPROVE="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) log_err "Unknown argument: $1"; usage; exit 2 ;;
  esac
done

[[ -z "$INSTANCE" ]] && { log_err "--name requires a non-empty value."; exit 2; }

confirm() {
  local prompt="$1"
  if [[ "$AUTO_APPROVE" == "true" ]]; then return 0; fi
  printf "${YELLOW}%s [y/N]: ${NC}" "$prompt"
  read -r reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

do_deallocate() {
  require_tools az
  require_az_login
  resolve_names "$INSTANCE"
  if ! vm_exists "$RG" "$VM"; then
    log_err "VM '${VM}' not found in resource group '${RG}'."
    log_err "Wrong instance/subscription, or it was never provisioned. Nothing deallocated."
    exit 5
  fi
  log_info "Target: VM '${VM}' in resource group '${RG}'."
  if ! confirm "Deallocate the VM (stops GPU billing, keeps disk and IP)?"; then
    log_warn "Aborted. No changes made."; exit 0
  fi
  log_info "Deallocating..."
  az vm deallocate --resource-group "$RG" --name "$VM" \
    ${SUB_OPT[@]+"${SUB_OPT[@]}"} --output none
  log_ok "VM deallocated. GPU compute billing stopped."
  log_warn "You still pay for the Premium OS disk and the static public IP."
  log_info "Resume later with: scripts/start.sh --name ${INSTANCE}"
}

do_start() {
  require_tools az
  require_az_login
  resolve_names "$INSTANCE"
  if ! vm_exists "$RG" "$VM"; then
    log_err "VM '${VM}' not found in resource group '${RG}'."
    log_err "Wrong instance/subscription, or it was never provisioned. Nothing started."
    exit 5
  fi
  log_info "Target: VM '${VM}' in resource group '${RG}'."
  log_info "Starting..."
  # Note: as a Spot VM, start can fail if there is no spot capacity right now.
  if az vm start --resource-group "$RG" --name "$VM" \
       ${SUB_OPT[@]+"${SUB_OPT[@]}"} --output none; then
    log_ok "VM started."
  else
    log_err "Start failed. For a Spot VM this often means no spot capacity is"
    log_err "currently available in the region. Try again later."
    exit 6
  fi
}

do_destroy() {
  require_tools az terraform
  require_az_login
  # --destroy is the only mode that genuinely needs Terraform state. Surface a
  # clear error if it is not initialized, instead of failing silently.
  if [[ ! -d "${TF_DIR}/.terraform" ]]; then
    log_err "Terraform is not initialized in ${TF_DIR}; cannot destroy from this checkout."
    log_err "Initialize it first: (cd infra/terraform && terraform init)"
    log_err "To only stop billing without Terraform, use: scripts/stop.sh --name ${INSTANCE}"
    exit 5
  fi
  cd "$TF_DIR"
  if ! terraform workspace select "$INSTANCE" 2>/dev/null; then
    log_err "Terraform workspace '${INSTANCE}' does not exist. Available:"
    terraform workspace list >&2 || true
    exit 5
  fi
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
