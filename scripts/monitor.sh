#!/usr/bin/env bash
#
# monitor.sh - Read-only status + live cost dashboard for the A100 GPU dev VMs.
#
# For every VM in the resource group it shows:
#   - power state (running / deallocated / stopped)
#   - size/SKU, location, purchasing model (Spot vs Regular)
#   - public IP and SSH reachability (port 22)
#   - running-since timestamp and elapsed time
#   - the live hourly rate (Azure Retail Prices API) and the ACCRUED COMPUTE COST
#     since the VM was (last) started
#   - optional GPU check (nvidia-smi over SSH) with --gpu
#
# The cost is an ESTIMATE of COMPUTE only (the VM hours). It does NOT include the
# OS disk, public IP, bandwidth, or any other resource, and Spot prices vary over
# time. It accrues only while a VM is running.
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
RG_OVERRIDE=""
SUBSCRIPTION=""
CURRENCY="USD"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Read-only status and live cost dashboard for the A100 GPU dev VMs.

Options:
  -g, --resource-group <name>   Resource group to inspect.
                                Default: from terraform output, else ai-devel-a100-rg.
  -s, --subscription <id-name>  Subscription to use (default: az CLI default).
      --gpu                     SSH into each running VM and run nvidia-smi.
      --watch <secs>            Refresh continuously every <secs> seconds.
  -h, --help                    Show this help.

Cost note:
  The accrued cost is a COMPUTE-ONLY estimate (rate x running hours from the
  Azure Retail Prices API). It excludes disk, IP, and bandwidth, and Spot prices
  vary. It accrues only while a VM is running.
EOF
}

# --- Parse args ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -g|--resource-group) RG_OVERRIDE="${2:-}"; shift 2 ;;
    -s|--subscription)   SUBSCRIPTION="${2:-}"; shift 2 ;;
    --gpu) DO_GPU="true"; shift ;;
    --watch) WATCH_INTERVAL="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) log_err "Unknown argument: $1"; usage; exit 2 ;;
  esac
done

# Optional "--subscription" arguments appended to every az call. Guarded for
# bash 3.2 (macOS) under set -u.
SUB_OPT=()
[[ -n "$SUBSCRIPTION" ]] && SUB_OPT=(--subscription "$SUBSCRIPTION")

# --- Prerequisites ---------------------------------------------------------
check_prereqs() {
  for tool in az python3 curl; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      log_err "Required tool not found: $tool"; exit 3
    fi
  done
  if ! az account show "${SUB_OPT[@]+"${SUB_OPT[@]}"}" >/dev/null 2>&1; then
    log_err "Not logged in to Azure (or subscription not accessible). Run: az login"; exit 4
  fi
}

# --- Resolve the resource group --------------------------------------------
resolve_rg() {
  if [[ -n "$RG_OVERRIDE" ]]; then
    RG="$RG_OVERRIDE"; return
  fi
  RG="$(terraform -chdir="$TF_DIR" output -raw resource_group_name 2>/dev/null || echo "")"
  [[ -z "$RG" ]] && RG="ai-devel-a100-rg"
}

# --- SSH reachability ------------------------------------------------------
check_ssh() {
  local ip="$1"
  [[ -z "$ip" || "$ip" == "None" ]] && return 1
  if command -v nc >/dev/null 2>&1; then
    nc -z -w 5 "$ip" 22 >/dev/null 2>&1
  else
    timeout 5 bash -c "cat < /dev/null > /dev/tcp/${ip}/22" >/dev/null 2>&1
  fi
}

# --- Live hourly rate from the Azure Retail Prices API ---------------------
# Args: region size priority(Spot|Regular). Echoes a USD/hour float or nothing.
get_rate() {
  local region="$1" size="$2" prio="$3"
  curl -s -G "https://prices.azure.com/api/retail/prices" \
    --data-urlencode "\$filter=armRegionName eq '$region' and armSkuName eq '$size' and priceType eq 'Consumption'" \
    2>/dev/null | python3 -c "
import sys, json
prio = '$prio'
try:
    items = json.load(sys.stdin).get('Items', [])
except Exception:
    sys.exit(0)
for x in items:
    if 'Windows' in (x.get('productName') or ''):
        continue
    sku = x.get('skuName') or ''
    if prio == 'Spot':
        if sku.endswith('Spot'):
            print(x['retailPrice']); break
    else:
        if 'Spot' not in sku and 'Low Priority' not in sku:
            print(x['retailPrice']); break
"
}

# --- Elapsed + accrued cost ------------------------------------------------
# Args: start_iso rate. Echoes tab-separated: "<Hh Mm>\t<cost>\t<hours>".
# Empty rate -> cost/hours blank.
elapsed_and_cost() {
  local start="$1" rate="$2"
  python3 - "$start" "$rate" <<'PY'
import sys
from datetime import datetime, timezone
start = sys.argv[1]
rate = sys.argv[2]
try:
    s = datetime.fromisoformat(start.replace('Z', '+00:00'))
except Exception:
    print("\t\t"); raise SystemExit
now = datetime.now(timezone.utc)
sec = max(0.0, (now - s).total_seconds())
h = int(sec // 3600); m = int((sec % 3600) // 60)
if rate:
    cost = float(rate) * sec / 3600.0
    print(f"{h}h {m}m\t{cost:.2f}\t{sec/3600:.4f}")
else:
    print(f"{h}h {m}m\t\t{sec/3600:.4f}")
PY
}

dashboard() {
  resolve_rg

  echo "==============================================================="
  echo " A100 GPU dev VMs   ($(date '+%Y-%m-%d %H:%M:%S'))"
  local sub_name
  sub_name="$(az account show "${SUB_OPT[@]+"${SUB_OPT[@]}"}" --query name -o tsv 2>/dev/null || echo '?')"
  printf " Subscription   : %s\n" "$sub_name"
  printf " Resource group : %s\n" "$RG"
  echo "==============================================================="

  # Enumerate VMs in the resource group.
  local vms
  vms="$(az vm list -g "$RG" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" --query "[].name" -o tsv 2>/dev/null || echo "")"
  if [[ -z "$vms" ]]; then
    c_warn " No virtual machines found in resource group '${RG}'."; echo
    echo " (Has the environment been provisioned? Run scripts/provision.sh)"
    echo "==============================================================="
    return
  fi

  local total_cost="0"
  local accruing="false"

  local vm
  while IFS= read -r vm; do
    [[ -z "$vm" ]] && continue

    # Core properties in a single call (array preserves order).
    local props size location prio created vmid
    props="$(az vm show -g "$RG" -n "$vm" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" \
      --query "[hardwareProfile.vmSize, location, priority, timeCreated, id]" -o tsv 2>/dev/null || echo "")"
    IFS=$'\t' read -r size location prio created vmid <<<"$props"
    [[ -z "${prio:-}" || "$prio" == "None" ]] && prio="Regular"

    # Power state.
    local power
    power="$(az vm get-instance-view -g "$RG" -n "$vm" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" \
      --query "instanceView.statuses[?starts_with(code,'PowerState/')].code | [0]" -o tsv 2>/dev/null | sed 's#PowerState/##' || echo "unknown")"
    [[ -z "$power" ]] && power="unknown"

    # Public IP.
    local ip
    ip="$(az vm list-ip-addresses -g "$RG" -n "$vm" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" \
      --query "[0].virtualMachine.network.publicIpAddresses[0].ipAddress" -o tsv 2>/dev/null || echo "")"

    # Running-since: last successful Start action, else creation time.
    local last_start running_since
    last_start="$(az monitor activity-log list --resource-id "$vmid" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" \
      --offset 90d --query "[?operationName.value=='Microsoft.Compute/virtualMachines/start/action' && status.value=='Succeeded'].eventTimestamp | [0]" \
      -o tsv 2>/dev/null || echo "")"
    if [[ -n "$last_start" && "$last_start" != "None" ]]; then
      running_since="$last_start"
    else
      running_since="$created"
    fi

    # Live rate + accrued cost (only meaningful while running).
    local rate elapsed cost hours
    rate="$(get_rate "$location" "$size" "$prio" 2>/dev/null || echo "")"
    IFS=$'\t' read -r elapsed cost hours < <(elapsed_and_cost "$running_since" "$rate")

    # --- Print VM block ---
    echo "---------------------------------------------------------------"
    printf " VM             : %s\n" "$vm"
    printf " Size / model   : %s  (%s)\n" "$size" "$prio"
    printf " Location       : %s\n" "$location"
    printf " Public IP      : %s\n" "${ip:-none}"

    printf " Power state    : "
    case "$power" in
      running)     c_ok "running"; echo ;;
      deallocated) c_warn "deallocated (compute billing stopped)"; echo ;;
      stopped)     c_warn "stopped (still allocated - may incur charges)"; echo ;;
      *)           c_err "$power"; echo ;;
    esac

    printf " SSH (port 22)  : "
    if [[ "$power" == "running" ]]; then
      if check_ssh "$ip"; then c_ok "reachable"; echo; else c_warn "not reachable (booting / NSG / firewall)"; echo; fi
    else
      c_warn "skipped (not running)"; echo
    fi

    # Rate line.
    if [[ -n "$rate" ]]; then
      printf " Hourly rate    : \$%s /hour  (%s, Linux, %s)\n" "$rate" "$prio" "$location"
    else
      printf " Hourly rate    : "; c_warn "unavailable from Retail Prices API"; echo
    fi

    # Cost line - only accrue while running.
    if [[ "$power" == "running" ]]; then
      accruing="true"
      printf " Running since  : %s  (%s)\n" "$running_since" "$elapsed"
      if [[ -n "$cost" ]]; then
        printf " Accrued cost   : "; c_ok "\$${cost}"; printf "  (compute only, est.)\n"
        total_cost="$(awk -v a="$total_cost" -v b="$cost" 'BEGIN{printf "%.2f", a+b}')"
      else
        printf " Accrued cost   : "; c_warn "n/a (no rate)"; echo
      fi
    else
      printf " Accrued cost   : "; c_warn "not accruing (VM not running)"; echo
      printf "                  (compute billing stops when deallocated; disk + IP still bill)\n"
    fi

    # Optional GPU check.
    if [[ "$DO_GPU" == "true" && "$power" == "running" ]] && check_ssh "$ip"; then
      echo " GPU (nvidia-smi):"
      local admin
      admin="$(terraform -chdir="$TF_DIR" output -raw admin_username 2>/dev/null || echo "azureuser")"
      if ! ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
            "${admin}@${ip}" "nvidia-smi" 2>/dev/null; then
        c_warn " Could not run nvidia-smi (SSH key not loaded, or driver not ready)."; echo
      fi
    fi
  done <<<"$vms"

  echo "==============================================================="
  if [[ "$accruing" == "true" ]]; then
    printf " TOTAL accrued (running VMs, compute only): "; c_ok "\$${total_cost}"; echo
  else
    c_warn " No running VMs - nothing accruing right now."; echo
  fi
  c_warn " Estimate excludes disk, public IP, and bandwidth. Spot prices vary."; echo
  echo "==============================================================="
}

main() {
  check_prereqs
  if [[ -n "$WATCH_INTERVAL" ]]; then
    if ! [[ "$WATCH_INTERVAL" =~ ^[0-9]+$ ]] || [[ "$WATCH_INTERVAL" -lt 1 ]]; then
      log_err "--watch requires a positive integer number of seconds."; exit 2
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
