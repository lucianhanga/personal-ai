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
INSTANCE="devel"    # instance to inspect; selects its Terraform workspace + RG.
NAME_SET="false"    # whether --name was given explicitly (for --all conflict check).
DO_ALL="false"      # iterate every named instance (workspace) instead of one.
DO_GPU="false"
WATCH_INTERVAL=""
RG_OVERRIDE=""
SUBSCRIPTION=""
CURRENCY="USD"
DASH_SUBTOTAL="0"   # set by dashboard(): this instance's accrued compute cost.

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Read-only status and live cost dashboard for the A100 GPU dev VMs.

Options:
  -n, --name <name>             Instance to inspect (alias: --instance). Default: devel.
                                Selects that instance's Terraform workspace and
                                resource group.
      --all                     Inspect EVERY named instance (every Terraform
                                workspace except 'default') and print a combined
                                total accrued cost. Cannot be combined with --name.
  -g, --resource-group <name>   Resource group to inspect (overrides --name's RG).
                                Default: from terraform output, else ai-<name>-a100-rg.
  -s, --subscription <id-name>  Subscription to use (default: az CLI default).
      --gpu                     SSH into each running VM and run nvidia-smi.
      --watch <secs>            Refresh continuously every <secs> seconds.
  -h, --help                    Show this help.

Examples:
  $(basename "$0")                       # the default 'devel' instance
  $(basename "$0") --name train          # one named instance
  $(basename "$0") --all                 # every instance + combined total
  $(basename "$0") --all --watch 15      # live, all instances

Cost note:
  The accrued cost is a COMPUTE-ONLY estimate (rate x running hours from the
  Azure Retail Prices API). It excludes disk, IP, and bandwidth, and Spot prices
  vary. It accrues only while a VM is running.
EOF
}

# --- Parse args ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--name|--instance) INSTANCE="${2:-}"; NAME_SET="true"; shift 2 ;;
    --all) DO_ALL="true"; shift ;;
    -g|--resource-group) RG_OVERRIDE="${2:-}"; shift 2 ;;
    -s|--subscription)   SUBSCRIPTION="${2:-}"; shift 2 ;;
    --gpu) DO_GPU="true"; shift ;;
    --watch) WATCH_INTERVAL="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) log_err "Unknown argument: $1"; usage; exit 2 ;;
  esac
done

# --all and --name are mutually exclusive; refuse rather than guess.
if [[ "$DO_ALL" == "true" && "$NAME_SET" == "true" ]]; then
  log_err "Use either --name <name> or --all, not both."; exit 2
fi
if [[ "$DO_ALL" != "true" && -z "$INSTANCE" ]]; then
  log_err "--name requires a non-empty value."; exit 2
fi

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

# --- Resolve the resource group for the current INSTANCE --------------------
# Selects the instance's Terraform workspace (read-only; never creates one),
# then prefers its resource_group_name output. Resource names are deterministic
# from the instance name, so we fall back to "ai-<instance>-a100-rg" whenever the
# output is unavailable (no terraform, no state, failed/destroyed instance).
resolve_rg() {
  if [[ -n "$RG_OVERRIDE" ]]; then
    RG="$RG_OVERRIDE"; return
  fi
  RG=""
  if terraform -chdir="$TF_DIR" workspace select "$INSTANCE" >/dev/null 2>&1; then
    RG="$(terraform -chdir="$TF_DIR" output -raw resource_group_name 2>/dev/null || echo "")"
  fi
  [[ -z "$RG" ]] && RG="ai-${INSTANCE}-a100-rg"
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
  DASH_SUBTOTAL="0"   # this instance's accrued compute cost (for --all totals).
  resolve_rg

  echo "==============================================================="
  echo " A100 GPU dev VMs   ($(date '+%Y-%m-%d %H:%M:%S'))"
  local sub_name
  sub_name="$(az account show "${SUB_OPT[@]+"${SUB_OPT[@]}"}" --query name -o tsv 2>/dev/null || echo '?')"
  printf " Instance       : %s\n" "$INSTANCE"
  printf " Subscription   : %s\n" "$sub_name"
  printf " Resource group : %s\n" "$RG"
  echo "==============================================================="

  # Enumerate VMs in the resource group.
  local vms
  vms="$(az vm list -g "$RG" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" --query "[].name" -o tsv 2>/dev/null || echo "")"
  if [[ -z "$vms" ]]; then
    c_warn " Instance '${INSTANCE}': no VM (resource group '${RG}' is empty or absent)."; echo
    echo " (Provision it with: scripts/provision.sh --name ${INSTANCE})"
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

  # Expose this instance's accrued total so --all can sum across instances.
  DASH_SUBTOTAL="$total_cost"

  echo "==============================================================="
  if [[ "$accruing" == "true" ]]; then
    printf " TOTAL accrued (running VMs, compute only): "; c_ok "\$${total_cost}"; echo
  else
    c_warn " No running VMs - nothing accruing right now."; echo
  fi
  c_warn " Estimate excludes disk, public IP, and bandwidth. Spot prices vary."; echo
  echo "==============================================================="
}

# --- Inspect every named instance (workspace) ------------------------------
# Enumerates Terraform workspaces, skips "default", and prints a dashboard for
# each remaining instance, then a combined total. Handles the empty cases
# (no terraform, no workspaces, only "default") gracefully and never aborts the
# loop because one instance has no VM.
run_all() {
  local ws_raw all_ws ws grand="0" found="false"

  ws_raw="$(terraform -chdir="$TF_DIR" workspace list 2>/dev/null || echo "")"
  # Strip the "*" current-workspace marker and surrounding whitespace; drop
  # blanks and the "default" workspace. One instance name per line.
  all_ws="$(printf '%s\n' "$ws_raw" \
    | sed 's/^[*[:space:]]*//; s/[[:space:]]*$//' \
    | awk 'NF && $0 != "default"')"

  if [[ -z "$all_ws" ]]; then
    echo "==============================================================="
    echo " A100 GPU dev VMs   ($(date '+%Y-%m-%d %H:%M:%S'))"
    echo "==============================================================="
    c_warn " No named instances found."; echo
    echo " Create one: scripts/provision.sh --name <name>"
    echo "==============================================================="
    return 0
  fi

  while IFS= read -r ws; do
    [[ -z "$ws" ]] && continue
    INSTANCE="$ws"
    RG_OVERRIDE=""        # always resolve each instance's own RG from its state.
    dashboard
    grand="$(awk -v a="$grand" -v b="${DASH_SUBTOTAL:-0}" 'BEGIN{printf "%.2f", a+b}')"
    found="true"
  done <<<"$all_ws"

  echo "==============================================================="
  if [[ "$found" == "true" ]]; then
    printf " COMBINED TOTAL accrued across all instances (compute only): "
    c_ok "\$${grand}"; echo
  fi
  c_warn " Estimate excludes disk, public IP, and bandwidth. Spot prices vary."; echo
  echo "==============================================================="
  return 0
}

# Render once: either one instance or all of them.
render() {
  if [[ "$DO_ALL" == "true" ]]; then
    run_all
  else
    dashboard
  fi
}

# Restore the originally-selected workspace on exit so the tool leaves no trace
# of which workspace it switched to while inspecting instances.
ORIG_WS=""
restore_workspace() {
  [[ -n "$ORIG_WS" ]] || return 0
  terraform -chdir="$TF_DIR" workspace select "$ORIG_WS" >/dev/null 2>&1 || true
}

main() {
  check_prereqs

  # Remember the active workspace (if terraform is usable) and restore it later.
  ORIG_WS="$(terraform -chdir="$TF_DIR" workspace show 2>/dev/null || echo "")"
  trap restore_workspace EXIT

  if [[ -n "$WATCH_INTERVAL" ]]; then
    if ! [[ "$WATCH_INTERVAL" =~ ^[0-9]+$ ]] || [[ "$WATCH_INTERVAL" -lt 1 ]]; then
      log_err "--watch requires a positive integer number of seconds."; exit 2
    fi
    while true; do
      clear
      render
      sleep "$WATCH_INTERVAL"
    done
  else
    render
  fi
}

main "$@"
