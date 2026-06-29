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

# --- Dedicated SSH key (created once, reused by every VM instance) ----------
# Matches the terraform variable default ssh_public_key_path. Using one stable
# key means the same key authenticates to every VM this project ever creates.
SSH_KEY_PATH="${HOME}/.ssh/ai-a100-devel"

# --- Defaults --------------------------------------------------------------
INSTANCE="devel"    # instance name; selects the Terraform workspace + resource names.
AUTO_APPROVE="false"
SSH_CIDR=""
REGION=""
REGION_SET="false"
ON_DEMAND="false"   # true -> provision a Regular (on-demand) VM instead of Spot.
DEVTOOLS="true"     # false -> skip the cloud-init developer toolchain install.
SKIP_MODELS="false" # true -> install tools but do not pre-pull Ollama models.

# Known Azure region short-names, grouped. Used for --help discoverability and
# to warn (not block) on an unrecognized --region value.
US_REGIONS="eastus eastus2 centralus northcentralus southcentralus westcentralus westus westus2 westus3"
EU_REGIONS="northeurope westeurope swedencentral uksouth ukwest francecentral germanywestcentral norwayeast switzerlandnorth polandcentral italynorth spaincentral"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Provision the Azure A100 GPU development VM with Terraform.

Options:
  -n, --name <name>         Instance name (alias: --instance). Default: devel.
                            Each name gets its own resource group, network, VM,
                            and Terraform workspace/state, so you can run several
                            instances at once - even in the same region. The
                            default 'devel' reproduces the original names.
  -y, --auto-approve        Skip the interactive confirmation before apply.
  -r, --region <region>     Azure region to deploy into (alias: --location).
                            Overrides 'location' in terraform.tfvars for this run.
                            Default: whatever terraform.tfvars / the variable sets.
      --on-demand           Provision a Regular (on-demand) VM instead of Spot
                            (aliases: --regular, --no-spot). Regular draws from
                            the "Standard NCADS_A100_v4 Family vCPUs" quota (not
                            the Spot/low-priority pool); it is more expensive but
                            is not evictable. Default is Spot.
      --ssh-cidr <CIDR>     Source CIDR allowed to reach SSH (port 22).
                            Default: auto-detected current public IP as /32.
      --no-devtools         Do NOT install the developer toolchain on first boot
                            (default: install uv/Python, Node/pnpm, Docker,
                            Ollama, gh and pre-pull the shared Ollama models).
      --skip-models         Install the toolchain but do NOT pre-pull the ~21 GB
                            Ollama models (pull them on first use instead).
  -h, --help                Show this help.

Regions (short-names):
  US:
      eastus, eastus2, centralus, northcentralus, southcentralus,
      westcentralus, westus, westus2, westus3
  Europe:
      northeurope, westeurope, swedencentral, uksouth, ukwest,
      francecentral, germanywestcentral, norwayeast, switzerlandnorth,
      polandcentral, italynorth, spaincentral

Examples:
  $(basename "$0") --region northeurope -y
  $(basename "$0") --name train --region eastus
  $(basename "$0") --name web   --region eastus     # second VM, same region
  $(basename "$0") --region eastus --on-demand

Notes:
  - By default this creates a SPOT VM. Azure can evict it when capacity is needed.
  - SSH is restricted to a single source CIDR (never '*').
EOF
}

# --- Parse args ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--name|--instance) INSTANCE="${2:-}"; shift 2 ;;
    -y|--auto-approve) AUTO_APPROVE="true"; shift ;;
    -r|--region|--location) REGION="${2:-}"; REGION_SET="true"; shift 2 ;;
    --on-demand|--regular|--no-spot) ON_DEMAND="true"; shift ;;
    --no-devtools) DEVTOOLS="false"; shift ;;
    --skip-models) SKIP_MODELS="true"; shift ;;
    --ssh-cidr) SSH_CIDR="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) log_err "Unknown argument: $1"; usage; exit 2 ;;
  esac
done

# --- Validate region (if provided) -----------------------------------------
# Empty -> hard fail (the flag was given without a value). Unrecognized short-
# name -> warn but proceed (it may still be a valid Azure region we don't list).
validate_region() {
  [[ -z "$REGION" && "${REGION_SET:-false}" == "true" ]] && { log_err "--region requires a non-empty value."; exit 2; }
  [[ -z "$REGION" ]] && return 0
  local r
  for r in $US_REGIONS $EU_REGIONS; do
    [[ "$r" == "$REGION" ]] && { log_ok "Region: ${REGION}"; return 0; }
  done
  log_warn "Region '${REGION}' is not in the known short-name list; proceeding anyway (it may still be valid)."
}

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

# --- Ensure the dedicated SSH key exists (create once) ---------------------
ensure_ssh_key() {
  if [[ -f "${SSH_KEY_PATH}.pub" ]]; then
    log_ok "Using dedicated SSH key: ${SSH_KEY_PATH}.pub"
    return
  fi
  log_warn "Dedicated SSH key not found. Creating it once: ${SSH_KEY_PATH}"
  if ssh-keygen -t ed25519 -N "" -C "ai-a100-devel" -f "${SSH_KEY_PATH}" >/dev/null 2>&1; then
    log_ok "Created dedicated SSH key: ${SSH_KEY_PATH}.pub (reused for every VM)."
  else
    log_err "Failed to create SSH key at ${SSH_KEY_PATH}."
    exit 7
  fi
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

  # Per-instance state: select (or create) the workspace named after the
  # instance. Each instance therefore gets isolated state and never collides
  # with another instance, even in the same region.
  log_info "Selecting Terraform workspace: ${INSTANCE}"
  terraform workspace select "$INSTANCE" 2>/dev/null || terraform workspace new "$INSTANCE"

  # Optional region override. When set, it is baked into the saved plan
  # (tfplan), so the subsequent apply uses it without re-specifying -var
  # (terraform forbids -var alongside a saved plan file).
  local tf_region_var=()
  if [[ -n "$REGION" ]]; then
    tf_region_var=(-var "location=${REGION}")
    log_info "Overriding location for this run: ${REGION}"
  fi

  # Optional purchasing-model override. Default (no flag) leaves vm_priority at
  # its "Spot" default; --on-demand switches it to Regular for this run.
  local tf_priority_var=()
  if [[ "$ON_DEMAND" == "true" ]]; then
    tf_priority_var=(-var "vm_priority=Regular")
    log_info "Purchasing model for this run: Regular (on-demand, not evictable)."
  fi

  # Developer toolchain toggles (cloud-init). Defaults install tools + models.
  local prepull="true"
  [[ "$SKIP_MODELS" == "true" ]] && prepull="false"
  if [[ "$DEVTOOLS" == "true" ]]; then
    log_info "Developer toolchain: install on first boot (prepull models: ${prepull})."
  else
    log_info "Developer toolchain: skipped (--no-devtools)."
  fi

  log_info "Running terraform plan..."
  terraform plan -input=false \
    -var "instance=${INSTANCE}" \
    -var "ssh_source_address_prefix=${SSH_CIDR}" \
    -var "enable_devtools=${DEVTOOLS}" \
    -var "prepull_models=${prepull}" \
    "${tf_region_var[@]+"${tf_region_var[@]}"}" \
    "${tf_priority_var[@]+"${tf_priority_var[@]}"}" \
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
  if [[ "$ON_DEMAND" == "true" ]]; then
    log_info "This is a REGULAR (on-demand) VM: not evictable, billed at on-demand rates."
  else
    log_warn "This is a SPOT VM. Azure may evict it when capacity is needed."
  fi
  log_warn "Stop GPU billing when idle:  scripts/stop.sh --name ${INSTANCE}"
}

main() {
  [[ -z "$INSTANCE" ]] && { log_err "--name requires a non-empty value."; exit 2; }
  log_ok "Instance: ${INSTANCE}"
  validate_region
  check_prereqs
  ensure_ssh_key
  detect_ssh_cidr
  accept_terms
  run_terraform
}

main "$@"
