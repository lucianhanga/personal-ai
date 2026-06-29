#!/usr/bin/env bash
#
# provision.sh - Accept marketplace terms and provision the A100 GPU dev VM.
#
# Steps:
#   1. Verify prerequisites (az, terraform, active az login).
#   2. Accept the NVIDIA NGC marketplace image terms.
#   3. Detect the operator public IP and restrict SSH to it (unless overridden).
#   4. terraform init + plan + apply (confirmation required unless -y).
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

# --- Marketplace image coordinates (must match terraform defaults) ---------
IMG_PUBLISHER="nvidia"
IMG_OFFER="ngc_azure_17_11"
IMG_SKU="ngc-base-version-25_9_1_gen2"

# --- Defaults --------------------------------------------------------------
AUTO_APPROVE="false"
SSH_CIDR=""

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Provision the Azure A100 GPU development VM with Terraform.

Options:
  -y, --auto-approve        Skip the interactive confirmation before apply.
      --ssh-cidr <CIDR>     Source CIDR allowed to reach SSH (port 22).
                            Default: auto-detected current public IP as /32.
  -h, --help                Show this help.

Notes:
  - This creates a SPOT VM. Azure can evict it when capacity is needed.
  - SSH is restricted to a single source CIDR (never '*').
EOF
}

# --- Parse args ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--auto-approve) AUTO_APPROVE="true"; shift ;;
    --ssh-cidr) SSH_CIDR="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) log_err "Unknown argument: $1"; usage; exit 2 ;;
  esac
done

# --- Prerequisite checks ---------------------------------------------------
check_prereqs() {
  local missing=0
  for tool in az terraform; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      log_err "Required tool not found: $tool"
      missing=1
    fi
  done
  [[ "$missing" -eq 0 ]] || exit 3

  if ! az account show >/dev/null 2>&1; then
    log_err "Not logged in to Azure. Run: az login"
    exit 4
  fi
  local sub
  sub="$(az account show --query name -o tsv)"
  log_ok "Azure login active. Subscription: ${sub}"
}

# --- Detect public IP ------------------------------------------------------
detect_ssh_cidr() {
  if [[ -n "$SSH_CIDR" ]]; then
    log_ok "Using provided SSH source CIDR: ${SSH_CIDR}"
    return
  fi
  local ip=""
  ip="$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || true)"
  if [[ -z "$ip" ]]; then
    ip="$(curl -fsS --max-time 10 https://ifconfig.me 2>/dev/null || true)"
  fi
  if [[ -z "$ip" ]]; then
    log_err "Could not auto-detect your public IP. Re-run with --ssh-cidr <CIDR>."
    exit 5
  fi
  SSH_CIDR="${ip}/32"
  log_ok "Detected public IP. SSH will be restricted to: ${SSH_CIDR}"
}

# --- Accept marketplace terms ----------------------------------------------
accept_terms() {
  log_info "Checking NVIDIA NGC marketplace image terms..."
  local accepted
  accepted="$(az vm image terms show \
    --publisher "$IMG_PUBLISHER" --offer "$IMG_OFFER" --plan "$IMG_SKU" \
    --query accepted -o tsv 2>/dev/null || echo "false")"
  if [[ "$accepted" == "true" ]]; then
    log_ok "Marketplace terms already accepted."
    return
  fi
  log_warn "Marketplace terms not accepted. Accepting now..."
  if az vm image terms accept \
      --publisher "$IMG_PUBLISHER" --offer "$IMG_OFFER" --plan "$IMG_SKU" \
      >/dev/null 2>&1; then
    log_ok "Marketplace terms accepted."
  else
    log_err "Failed to accept marketplace terms for ${IMG_PUBLISHER}:${IMG_OFFER}:${IMG_SKU}."
    exit 6
  fi
}

# --- Terraform -------------------------------------------------------------
run_terraform() {
  cd "$TF_DIR"

  log_info "Running terraform init..."
  terraform init -input=false

  log_info "Running terraform plan..."
  terraform plan -input=false \
    -var "ssh_source_address_prefix=${SSH_CIDR}" \
    -out=tfplan

  if [[ "$AUTO_APPROVE" != "true" ]]; then
    printf "${YELLOW}Apply this plan and create the A100 Spot VM? [y/N]: ${NC}"
    read -r reply
    if [[ ! "$reply" =~ ^[Yy]$ ]]; then
      log_warn "Aborted by user. No changes applied."
      rm -f tfplan
      exit 0
    fi
  fi

  log_info "Running terraform apply..."
  terraform apply -input=false tfplan
  rm -f tfplan

  log_ok "Provisioning complete."
  local conn
  conn="$(terraform output -raw ssh_connection_string 2>/dev/null || echo "")"
  if [[ -n "$conn" ]]; then
    printf "${GREEN}SSH connection:${NC} %s\n" "$conn"
  fi
  log_warn "This is a SPOT VM. Azure may evict it when capacity is needed."
  log_warn "Stop GPU billing when idle:  scripts/deprovision.sh --deallocate"
}

main() {
  check_prereqs
  detect_ssh_cidr
  accept_terms
  run_terraform
}

main "$@"
