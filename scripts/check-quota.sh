#!/usr/bin/env bash
#
# check-quota.sh - Survey Azure quota and SKU availability for the A100 dev VM.
#
# For each region (US, Europe, India by default) it reports whether you can
# provision a Standard_NC24ads_A100_v4 (24 vCPUs) as Regular and/or as Spot.
#
# Requirements checked per region:
#   - SKU offered and not restricted for your subscription.
#   - Regular: "Standard NCADS_A100_v4 Family vCPUs" AND "Total Regional vCPUs"
#              each have >= 24 vCPUs free (limit - current).
#   - Spot:    "Total Regional Low-priority vCPUs" has >= 24 vCPUs free.
#
# Note: the A100 family quota ("...NCADS_A100_v4 Family vCPUs") is what gates the
# specific NC24ads_A100_v4 size for Regular VMs. Spot has no family quota; it
# draws from the shared regional low-priority pool.
#
# This script is READ-ONLY. It changes nothing.
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

# --- Defaults --------------------------------------------------------------
SIZE="Standard_NC24ads_A100_v4"
REQUIRED=24            # vCPUs needed by the size above.
GEO="all"              # us | europe | india | all
CUSTOM_REGIONS=""
SUBSCRIPTION=""        # Optional explicit subscription id or name. Empty = CLI default.

# Region lists limited to where NC24ads_A100_v4 is actually offered to this
# subscription. Regions that returned 'absent'/'error' in the survey were
# removed (northcentralus, ukwest, norwayeast, southindia, westindia,
# jioindiawest, jioindiacentral).
US_REGIONS=(eastus eastus2 westus westus2 westus3 centralus southcentralus)
EU_REGIONS=(westeurope northeurope swedencentral uksouth francecentral germanywestcentral switzerlandnorth)
INDIA_REGIONS=(centralindia)

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Survey Azure A100 quota and SKU availability for provisioning ${SIZE}.

Options:
      --geo <set>        Region set: us | europe | india | all  (default: all)
      --regions <list>   Comma-separated regions to check instead of a geo set.
      --size <name>      VM size to check (default: ${SIZE}).
      --required <n>     vCPUs required (default: ${REQUIRED}, the size's vCPU count).
  -s, --subscription <id-or-name>
                         Run the whole survey against this subscription instead
                         of the az CLI default. Applied to every az call.
  -h, --help             Show this help.

Example:
  $(basename "$0") --subscription 2b86de39-5593-4d95-8e43-529f13606065 --regions northeurope

Columns:
  SKU           available / restricted / absent for your subscription.
  A100 vCPUs    free / limit for the NCADS_A100_v4 family (Regular gate).
  REGULAR       OK if SKU available and Regular quota satisfies ${REQUIRED} vCPUs.
  LOWPRI vCPUs  free / limit for the regional low-priority pool (Spot gate).
  SPOT          OK if SKU available and low-priority quota satisfies ${REQUIRED} vCPUs.
EOF
}

# --- Parse args ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --geo)      GEO="${2:-}"; shift 2 ;;
    --regions)  CUSTOM_REGIONS="${2:-}"; shift 2 ;;
    --size)     SIZE="${2:-}"; shift 2 ;;
    --required) REQUIRED="${2:-}"; shift 2 ;;
    -s|--subscription) SUBSCRIPTION="${2:-}"; shift 2 ;;
    -h|--help)  usage; exit 0 ;;
    *) log_err "Unknown argument: $1"; usage; exit 2 ;;
  esac
done

# --- Subscription scoping --------------------------------------------------
# SUB_OPT holds the optional "--subscription <id>" arguments appended to every
# az call. Empty when no --subscription was given (CLI default is used). The
# guarded expansion "${SUB_OPT[@]+...}" keeps this safe under bash 3.2's
# "set -u" (macOS default), where expanding an empty array would otherwise
# fail with an unbound-variable error.
SUB_OPT=()
if [[ -n "$SUBSCRIPTION" ]]; then
  SUB_OPT=(--subscription "$SUBSCRIPTION")
fi

# --- Prerequisites ---------------------------------------------------------
if ! command -v az >/dev/null 2>&1; then
  log_err "Required tool not found: az"; exit 3
fi
if ! az account show "${SUB_OPT[@]+"${SUB_OPT[@]}"}" >/dev/null 2>&1; then
  log_err "Not logged in to Azure (or the requested subscription is not accessible). Run: az login"; exit 4
fi

# --- Build region list -----------------------------------------------------
REGIONS=()
if [[ -n "$CUSTOM_REGIONS" ]]; then
  IFS=',' read -r -a REGIONS <<<"$CUSTOM_REGIONS"
else
  case "$GEO" in
    us)     REGIONS=("${US_REGIONS[@]}") ;;
    europe) REGIONS=("${EU_REGIONS[@]}") ;;
    india)  REGIONS=("${INDIA_REGIONS[@]}") ;;
    all)    REGIONS=("${US_REGIONS[@]}" "${EU_REGIONS[@]}" "${INDIA_REGIONS[@]}") ;;
    *) log_err "Invalid --geo '$GEO'. Use us | europe | india | all."; exit 2 ;;
  esac
fi

SUB_NAME="$(az account show "${SUB_OPT[@]+"${SUB_OPT[@]}"}" --query name -o tsv)"
SUB_ID="$(az account show "${SUB_OPT[@]+"${SUB_OPT[@]}"}" --query id -o tsv)"
log_info "Subscription : ${SUB_NAME} (${SUB_ID})"
log_info "Size         : ${SIZE} (requires ${REQUIRED} vCPUs)"
log_info "Regions      : ${#REGIONS[@]} (${GEO}${CUSTOM_REGIONS:+ custom})"
log_info ""

# --- Helpers ---------------------------------------------------------------
# Print a fixed-width cell, colored. Args: text width color.
cell() {
  local text="$1" width="$2" color="$3" padded
  padded="$(printf "%-*s" "$width" "$text")"
  printf "%b%s%b" "$color" "$padded" "$NC"
}

# --- Table header ----------------------------------------------------------
printf "%-18s %-12s %-12s %-8s %-13s %-6s\n" \
  "REGION" "SKU" "A100 vCPUs" "REGULAR" "LOWPRI vCPUs" "SPOT"
printf "%-18s %-12s %-12s %-8s %-13s %-6s\n" \
  "------" "---" "----------" "-------" "------------" "----"

# Result accumulators.
REGULAR_OK_REGIONS=()
SPOT_OK_REGIONS=()
REGIONAL_CAP_BLOCKED=()

# --- Per-region check ------------------------------------------------------
check_region() {
  local region="$1"

  # One call returns the three quota rows we care about.
  local usage
  if ! usage="$(az vm list-usage -l "$region" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" \
        --query "[?name.value=='lowPriorityCores' || name.value=='cores' || contains(name.value,'NCADSA100v4')].[name.value, currentValue, limit]" \
        -o tsv 2>/dev/null)"; then
    printf "%-18s " "$region"; cell "error" 12 "$RED"; printf "  (region unavailable / no access)\n"
    return
  fi

  local fam_cur=0 fam_lim=0 low_cur=0 low_lim=0 cores_cur=0 cores_lim=0
  local v cur lim
  while IFS=$'\t' read -r v cur lim; do
    [[ -z "${v:-}" ]] && continue
    case "$v" in
      lowPriorityCores) low_cur="${cur:-0}";   low_lim="${lim:-0}" ;;
      cores)            cores_cur="${cur:-0}"; cores_lim="${lim:-0}" ;;
      *NCADSA100v4*)    fam_cur="${cur:-0}";   fam_lim="${lim:-0}" ;;
    esac
  done <<<"$usage"

  local fam_avail=$(( fam_lim - fam_cur ))
  local low_avail=$(( low_lim - low_cur ))
  local cores_avail=$(( cores_lim - cores_cur ))

  # SKU availability (use --all to include restricted SKUs).
  local skuline sku_name sku_reason sku_status sku_color
  skuline="$(az vm list-skus -l "$region" --size "$SIZE" --all "${SUB_OPT[@]+"${SUB_OPT[@]}"}" \
    --query "[?name=='$SIZE'].[name, restrictions[0].reasonCode] | [0]" \
    -o tsv 2>/dev/null || true)"
  IFS=$'\t' read -r sku_name sku_reason <<<"${skuline:-}"
  if [[ -z "${sku_name:-}" ]]; then
    sku_status="absent";     sku_color="$YELLOW"
  elif [[ -z "${sku_reason:-}" ]]; then
    sku_status="available";  sku_color="$GREEN"
  else
    sku_status="restricted"; sku_color="$YELLOW"
  fi

  # Feasibility.
  local regular_ok="false" spot_ok="false"
  if [[ "$sku_status" == "available" ]]; then
    if (( fam_avail >= REQUIRED && cores_avail >= REQUIRED )); then
      regular_ok="true"
    elif (( fam_avail >= REQUIRED && cores_avail < REQUIRED )); then
      REGIONAL_CAP_BLOCKED+=("$region")
    fi
    if (( low_avail >= REQUIRED )); then
      spot_ok="true"
    fi
  fi

  local reg_word reg_color spot_word spot_color
  if [[ "$regular_ok" == "true" ]]; then reg_word="OK"; reg_color="$GREEN"; REGULAR_OK_REGIONS+=("$region")
  else reg_word="NO"; reg_color="$RED"; fi
  if [[ "$spot_ok" == "true" ]]; then spot_word="OK"; spot_color="$GREEN"; SPOT_OK_REGIONS+=("$region")
  else spot_word="NO"; spot_color="$RED"; fi

  printf "%-18s " "$region"
  cell "$sku_status" 12 "$sku_color"; printf " "
  printf "%-12s " "${fam_avail}/${fam_lim}"
  cell "$reg_word" 8 "$reg_color"
  printf "%-13s " "${low_avail}/${low_lim}"
  cell "$spot_word" 6 "$spot_color"
  printf "\n"
}

for r in "${REGIONS[@]}"; do
  check_region "$r"
done

# --- Summary ---------------------------------------------------------------
printf "\n"
log_info "==============================================================="
log_info " Summary (need ${REQUIRED} free vCPUs for ${SIZE})"
log_info "==============================================================="

if [[ ${#REGULAR_OK_REGIONS[@]} -gt 0 ]]; then
  log_ok "Regular (on-demand) ready in: ${REGULAR_OK_REGIONS[*]}"
else
  log_warn "Regular (on-demand): no region currently has enough family quota."
fi

if [[ ${#SPOT_OK_REGIONS[@]} -gt 0 ]]; then
  log_ok "Spot ready in: ${SPOT_OK_REGIONS[*]}"
else
  log_warn "Spot: no region currently has enough low-priority quota."
fi

if [[ ${#REGIONAL_CAP_BLOCKED[@]} -gt 0 ]]; then
  log_warn "Family quota was sufficient but the 'Total Regional vCPUs' cap is the"
  log_warn "limiter in: ${REGIONAL_CAP_BLOCKED[*]} (raise regional vCPUs too)."
fi

if [[ ${#REGULAR_OK_REGIONS[@]} -eq 0 && ${#SPOT_OK_REGIONS[@]} -eq 0 ]]; then
  printf "\n"
  log_warn "No region satisfies the requirement yet. Request a quota increase:"
  log_info "  Portal : https://aka.ms/ProdportalCRP (Quotas blade -> Compute)"
  log_info "  Raise 'Standard NCADS_A100_v4 Family vCPUs' to >= ${REQUIRED} for Regular,"
  log_info "  and/or 'Total Regional Low-priority vCPUs' to >= ${REQUIRED} for Spot,"
  log_info "  in a region where the SKU shows 'available' above."
  exit 1
fi

printf "\n"
log_ok "At least one region can provision ${SIZE}. Set 'location' (and"
log_info "'vm_priority') in terraform/terraform.tfvars accordingly, then run scripts/provision.sh."
exit 0
