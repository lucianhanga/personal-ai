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
# It ALSO surfaces the STANDING RESOURCES in each resource group - the public IP
# addresses and managed disks - with an estimated MONTHLY cost each, plus a
# per-instance standing subtotal. These bill 24/7 regardless of VM power state,
# so they are shown even when the VM is deallocated, failed, or was never created
# (a partial/failed provision with no VM still costs money for its IP and disk).
#
# Two distinct cost figures are reported:
#   - COMPUTE  : an hourly-rate estimate that accrues ONLY while a VM runs.
#   - STANDING : a monthly estimate for the always-on IP + disk resources.
#
# The compute cost excludes disk, IP, and bandwidth, and Spot prices vary over
# time. The standing cost is an estimate from the Azure Retail Prices API.
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

# --- Defaults --------------------------------------------------------------
INSTANCE="devel"    # only used when --name is given; selects RG ai-<name>-a100-rg.
NAME_SET="false"    # whether --name was given (single-instance vs. discover-all).
DO_ALL="false"      # explicit "inspect every Azure instance" (also the default).
DO_LIST="false"     # compact inventory table (one row per instance) instead of dashboards.
DO_TOP="false"      # full-screen live mode (alternate screen, redraw in place).
DO_GPU="false"
WATCH_INTERVAL=""
RG_OVERRIDE=""
SUBSCRIPTION=""
CURRENCY="USD"
DASH_SUBTOTAL="0"      # set by dashboard(): this instance's accrued compute cost.
DASH_STANDING="0"      # set by dashboard(): this instance's monthly standing cost.
STANDING_SUBTOTAL="0"  # set by standing_resources(): the section's monthly subtotal.
PRICE_CACHE_DIR=""     # per-run cache dir for Retail Prices lookups.

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Read-only status and live cost dashboard for the A100 GPU dev VMs.

Instances are DISCOVERED FROM AZURE (resource groups named ai-<name>-a100-rg),
not from local Terraform state, so the view always reflects what actually exists
in the subscription. With no flags, EVERY discovered instance is shown.

Options:
  -n, --name <name>             Inspect a SINGLE instance: its resource group
                                ai-<name>-a100-rg, read directly from Azure. If
                                that group does not exist, it says so gracefully.
      --all                     Inspect EVERY instance discovered in Azure and
                                print combined totals. This is also the DEFAULT
                                when no --name is given. Cannot combine with --name.
  -l, --list                    Compact INVENTORY table: one row per discovered
                                instance (INSTANCE, REGION, STATUS, RESOURCES,
                                STANDING $/mo) + a combined standing total.
                                STATUS is running / stopped / partial / empty;
                                'partial' = resources exist but no VM (a failed or
                                incomplete provision that is still billing).
  -g, --resource-group <name>   Resource group to inspect (overrides --name's RG).
                                Default: ai-<name>-a100-rg.
  -s, --subscription <id-name>  Subscription to use (default: az CLI default).
      --gpu                     SSH into each running VM and run nvidia-smi.
      --top, --live             Full-screen LIVE mode: take over the terminal
                                (alternate screen), redraw the dashboard (or the
                                --list table) in place every few seconds, and
                                restore the terminal on exit / Ctrl-C. Default
                                refresh is 5s; set it with --watch <secs>. If
                                stdout is not a TTY this degrades to one render.
      --watch <secs>            Live refresh every <secs> seconds (implies --top).
  -h, --help                    Show this help.

Examples:
  $(basename "$0")                       # ALL Azure instances + combined totals
  $(basename "$0") --name train          # one instance (ai-train-a100-rg)
  $(basename "$0") --list                # quick inventory table of every instance
  $(basename "$0") --top                 # full-screen live dashboard (5s refresh)
  $(basename "$0") --list --watch 10     # full-screen live inventory, 10s refresh

Cost note:
  Two distinct figures are reported, both from the Azure Retail Prices API:

    COMPUTE  - the accrued VM cost (hourly rate x running hours). It accrues
               ONLY while a VM is running and excludes disk, IP, and bandwidth.
               Spot prices vary over time.

    STANDING - a MONTHLY estimate for the resources that bill 24/7 regardless of
               VM power state: the public IP addresses and managed disks in the
               resource group. These keep costing money while the VM is stopped
               (deallocated), failed, or even when no VM exists at all (a
               partial/failed provision still has a billable IP and disk).

  Each instance dashboard prints the VM block, then a "Standing resources"
  section listing every public IP and managed disk with its estimated monthly
  cost and a per-instance standing subtotal. With --all you also get a combined
  standing monthly total alongside the combined accrued compute total.
EOF
}

# --- Parse args ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--name|--instance) INSTANCE="${2:-}"; NAME_SET="true"; shift 2 ;;
    --all) DO_ALL="true"; shift ;;
    -l|--list) DO_LIST="true"; shift ;;
    -g|--resource-group) RG_OVERRIDE="${2:-}"; shift 2 ;;
    -s|--subscription)   SUBSCRIPTION="${2:-}"; shift 2 ;;
    --gpu) DO_GPU="true"; shift ;;
    --watch) WATCH_INTERVAL="${2:-}"; DO_TOP="true"; shift 2 ;;
    --top|--live) DO_TOP="true"; shift ;;
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
# Monitor is a pure read-only Azure tool: it does NOT consult Terraform state or
# workspaces (which can be wiped or out of sync with Azure). Resource names are
# deterministic, so the RG is always "ai-<instance>-a100-rg" unless overridden.
resolve_rg() {
  if [[ -n "$RG_OVERRIDE" ]]; then
    RG="$RG_OVERRIDE"; return
  fi
  RG="ai-${INSTANCE}-a100-rg"
}

# --- Discover instances from AZURE (not Terraform) --------------------------
# Authoritative discovery: list resource groups named "ai-<instance>-a100-rg"
# (the project's deterministic pattern) and strip to the bare instance name.
# Reflects Azure reality regardless of local Terraform state. One name per line.
discover_instances() {
  az group list "${SUB_OPT[@]+"${SUB_OPT[@]}"}" \
    --query "[?starts_with(name,'ai-') && ends_with(name,'-a100-rg')].name" -o tsv 2>/dev/null \
    | sed -E 's/^ai-//; s/-a100-rg$//' \
    | awk 'NF' \
    | sort
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

# --- Retail price cache ----------------------------------------------------
# Tiny file-based cache keyed by "(kind|region|sku)" so repeated lookups (e.g.
# the same disk tier or IP SKU across instances) avoid extra curls. Uses files,
# not associative arrays, to stay bash 3.2 safe. A cached miss is stored as an
# empty file, so we never re-curl a known-missing price either.
cache_init() {
  PRICE_CACHE_DIR="$(mktemp -d 2>/dev/null || echo "/tmp/monitor-price-$$")"
  mkdir -p "$PRICE_CACHE_DIR" 2>/dev/null || true
}
cache_file() {
  printf '%s/%s' "$PRICE_CACHE_DIR" "$(printf '%s' "$1" | tr -c 'A-Za-z0-9' '_')"
}
# Echoes the cached value, or the literal "__MISS__" when not cached at all.
cache_lookup() {
  local f; f="$(cache_file "$1")"
  if [[ -f "$f" ]]; then cat "$f"; else printf '__MISS__'; fi
}
cache_store() {
  [[ -n "$PRICE_CACHE_DIR" ]] || return 0
  local f; f="$(cache_file "$1")"
  printf '%s' "$2" > "$f" 2>/dev/null || true
}

# --- Public IP hourly price (Azure Retail Prices API) ----------------------
# Args: region sku(Standard|Basic) allocation(Static|Dynamic).
# Echoes a USD/hour float, or nothing if it cannot be resolved. The meter names
# look like "Standard IPv4 Static Public IP" under productName 'IP Addresses'.
get_ip_hourly() {
  local region="$1" sku="$2" alloc="$3"
  local key="ip|${region}|${sku}|${alloc}" cached
  cached="$(cache_lookup "$key")"
  if [[ "$cached" != "__MISS__" ]]; then printf '%s' "$cached"; return; fi
  local val
  val="$(curl -s -G "https://prices.azure.com/api/retail/prices" \
    --data-urlencode "\$filter=serviceName eq 'Virtual Network' and armRegionName eq '$region' and priceType eq 'Consumption' and productName eq 'IP Addresses'" \
    2>/dev/null | python3 -c "
import sys, json
sku='$sku'; alloc='$alloc'
want = (sku + ' IPv4 ' + alloc + ' Public IP').lower()
try:
    items = json.load(sys.stdin).get('Items', [])
except Exception:
    sys.exit(0)
for x in items:
    if (x.get('meterName') or '').lower() == want:
        print(x['retailPrice']); break
")"
  cache_store "$key" "$val"
  printf '%s' "$val"
}

# --- Managed-disk tier resolution ------------------------------------------
# Args: storageType(Premium_LRS|StandardSSD_LRS|Standard_LRS) diskSizeGB.
# Rounds the size UP to the next provisioned tier and echoes "<sku>\t<product>"
# (e.g. "P10 LRS\tPremium SSD Managed Disks"), or nothing if unresolved.
disk_tier() {
  python3 - "$1" "$2" <<'PY'
import sys
stype = sys.argv[1]
try:
    size = float(sys.argv[2])
except Exception:
    print(""); raise SystemExit
fam = {
    'Premium_LRS':     ('P', 'Premium SSD Managed Disks'),
    'StandardSSD_LRS': ('E', 'Standard SSD Managed Disks'),
    'Standard_LRS':    ('S', 'Standard HDD Managed Disks'),
}
if stype not in fam:
    print(""); raise SystemExit
letter, product = fam[stype]
tiers = [(1,4),(2,8),(3,16),(4,32),(6,64),(10,128),(15,256),
         (20,512),(30,1024),(40,2048),(50,4096)]
sel = None
for num, gib in tiers:
    if size <= gib:
        sel = num; break
if sel is None:
    print(""); raise SystemExit
print("%s%d LRS\t%s" % (letter, sel, product))
PY
}

# --- Managed-disk monthly price (Azure Retail Prices API) ------------------
# Args: region sku(e.g. "P10 LRS") product(e.g. "Premium SSD Managed Disks").
# Echoes a USD/month float, or nothing. Meters are billed per "1/Month".
get_disk_monthly() {
  local region="$1" sku="$2" product="$3"
  local key="disk|${region}|${sku}" cached
  cached="$(cache_lookup "$key")"
  if [[ "$cached" != "__MISS__" ]]; then printf '%s' "$cached"; return; fi
  local val
  val="$(curl -s -G "https://prices.azure.com/api/retail/prices" \
    --data-urlencode "\$filter=serviceName eq 'Storage' and armRegionName eq '$region' and priceType eq 'Consumption' and unitOfMeasure eq '1/Month' and skuName eq '$sku' and productName eq '$product'" \
    2>/dev/null | python3 -c "
import sys, json
try:
    items = json.load(sys.stdin).get('Items', [])
except Exception:
    sys.exit(0)
if items:
    print(items[0]['retailPrice'])
")"
  cache_store "$key" "$val"
  printf '%s' "$val"
}

# --- Shared resource parsers -----------------------------------------------
# Turn `az ... -o json` output into tab-separated rows so the dashboard and the
# inventory (--list) share one source of truth. Both read stdin.
ip_rows_from_json() {
  python3 -c "
import sys, json
try:
    items = json.load(sys.stdin) or []
except Exception:
    items = []
for x in items:
    name   = x.get('name') or '?'
    sku    = ((x.get('sku') or {}).get('name')) or 'Basic'
    alloc  = x.get('publicIPAllocationMethod') or 'Dynamic'
    attach = 'attached' if x.get('ipConfiguration') else 'unattached'
    loc    = x.get('location') or ''
    print('\t'.join([name, sku, alloc, attach, loc]))
" 2>/dev/null
}
disk_rows_from_json() {
  python3 -c "
import sys, json
try:
    items = json.load(sys.stdin) or []
except Exception:
    items = []
for x in items:
    name = x.get('name') or '?'
    sku  = ((x.get('sku') or {}).get('name')) or '?'
    size = x.get('diskSizeGB')
    size = str(size) if size is not None else '0'
    loc  = x.get('location') or ''
    attach = 'attached' if x.get('managedBy') else 'unattached'
    print('\t'.join([name, sku, size, loc, attach]))
" 2>/dev/null
}

# Per-row monthly cost (shared by the dashboard and the inventory).
# ip_row_monthly:   args sku alloc attach loc  -> echoes monthly float, or "" if
#                   the price could not be resolved (a free row echoes "0.00").
ip_row_monthly() {
  local sku="$1" alloc="$2" attach="$3" loc="$4" rate
  if [[ "$alloc" == "Dynamic" && "$attach" == "unattached" ]]; then
    printf '0.00'; return
  fi
  rate="$(get_ip_hourly "$loc" "$sku" "$alloc" 2>/dev/null || echo "")"
  [[ -z "$rate" ]] && return
  awk -v r="$rate" 'BEGIN{printf "%.2f", r*730}'
}
# disk_row_monthly: args sku sizeGB loc -> echoes "monthly\ttierSku", or "" if
#                   the tier/price could not be resolved.
disk_row_monthly() {
  local sku="$1" size="$2" loc="$3" tier tsku tproduct m
  tier="$(disk_tier "$sku" "$size" 2>/dev/null || echo "")"
  [[ -z "$tier" ]] && return
  IFS=$'\t' read -r tsku tproduct <<<"$tier"
  m="$(get_disk_monthly "$loc" "$tsku" "$tproduct" 2>/dev/null || echo "")"
  [[ -z "$m" ]] && return
  printf '%s\t%s' "$(awk -v m="$m" 'BEGIN{printf "%.2f", m}')" "$tsku"
}

# --- Standing resources block ----------------------------------------------
# Args: resource_group  has_vm(yes|no). Enumerates the always-on billable
# resources (public IPs + managed disks) in the RG, prints each with an
# estimated monthly cost, and sets STANDING_SUBTOTAL to the section total.
# All reads are read-only; never aborts on missing data.
standing_resources() {
  local rg="$1" has_vm="$2"
  STANDING_SUBTOTAL="0"
  local monthly_total="0"

  echo " Standing resources (billed 24/7, regardless of VM state):"
  if [[ "$has_vm" == "no" ]]; then
    c_warn "   No VM present, but these resources still cost money."; echo
  fi

  # --- Public IPs ---
  local ip_json ip_rows
  ip_json="$(az network public-ip list -g "$rg" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" -o json 2>/dev/null || echo "[]")"
  ip_rows="$(printf '%s' "$ip_json" | ip_rows_from_json)"

  if [[ -z "$ip_rows" ]]; then
    printf "   Public IP   : %s\n" "none"
  else
    local ipname ipsku ipalloc ipattach iploc monthly note
    while IFS=$'\t' read -r ipname ipsku ipalloc ipattach iploc; do
      [[ -z "$ipname" ]] && continue
      note=""
      monthly="$(ip_row_monthly "$ipsku" "$ipalloc" "$ipattach" "$iploc")"
      if [[ "$ipalloc" == "Dynamic" && "$ipattach" == "unattached" ]]; then
        note="dynamic + unattached -> free"
      elif [[ -n "$monthly" ]]; then
        monthly_total="$(awk -v a="$monthly_total" -v b="$monthly" 'BEGIN{printf "%.2f", a+b}')"
      fi
      if [[ -n "$monthly" ]]; then
        printf "   Public IP   : %s  (%s, %s, %s)  ~\$%s/mo" \
          "$ipname" "$ipsku" "$ipalloc" "$ipattach" "$monthly"
        [[ -n "$note" ]] && printf "  [%s]" "$note"
        echo
      else
        printf "   Public IP   : %s  (%s, %s, %s)  " \
          "$ipname" "$ipsku" "$ipalloc" "$ipattach"
        c_warn "cost n/a (price not resolved)"; echo
      fi
    done <<<"$ip_rows"
  fi

  # --- Managed disks ---
  local disk_json disk_rows
  disk_json="$(az disk list -g "$rg" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" -o json 2>/dev/null || echo "[]")"
  disk_rows="$(printf '%s' "$disk_json" | disk_rows_from_json)"

  if [[ -z "$disk_rows" ]]; then
    printf "   Disk        : %s\n" "none"
  else
    local dname dsku dsize dloc dattach priced monthly tsku
    while IFS=$'\t' read -r dname dsku dsize dloc dattach; do
      [[ -z "$dname" ]] && continue
      priced="$(disk_row_monthly "$dsku" "$dsize" "$dloc")"
      if [[ -n "$priced" ]]; then
        IFS=$'\t' read -r monthly tsku <<<"$priced"
        monthly_total="$(awk -v a="$monthly_total" -v b="$monthly" 'BEGIN{printf "%.2f", a+b}')"
        printf "   Disk        : %s  (%s, %s GiB -> %s, %s)  ~\$%s/mo\n" \
          "$dname" "$dsku" "$dsize" "$tsku" "$dattach" "$monthly"
      else
        printf "   Disk        : %s  (%s, %s GiB, %s)  " \
          "$dname" "$dsku" "$dsize" "$dattach"
        c_warn "cost n/a (tier/price not resolved)"; echo
      fi
    done <<<"$disk_rows"
  fi

  STANDING_SUBTOTAL="$monthly_total"
  printf "   Standing monthly subtotal: "; c_ok "\$${monthly_total}"
  printf "  (est., bills 24/7)\n"
}

# --- Inventory row (for --list) --------------------------------------------
# Args: instance_name. Echoes one TSV record describing the instance's RG:
#   instance \t region \t status \t resources \t standing_monthly
# status: running | stopped | partial (resources but no VM) | empty.
# All reads are read-only; reuses the shared parsers + per-row pricing helpers.
inventory_row() {
  local name="$1" rg="ai-${name}-a100-rg"
  local region vmname power status resources standing="0"

  region="$(az group show -g "$rg" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" --query location -o tsv 2>/dev/null || echo "?")"
  [[ -z "$region" ]] && region="?"

  # VM presence, then authoritative power state from the instance view (the same
  # source the full dashboard uses; `az vm list -d` powerState can be transiently
  # empty and must not be trusted for classification).
  vmname="$(az vm list -g "$rg" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" --query "[0].name" -o tsv 2>/dev/null || echo "")"
  [[ "$vmname" == "None" ]] && vmname=""
  power=""
  if [[ -n "$vmname" ]]; then
    power="$(az vm get-instance-view -g "$rg" -n "$vmname" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" \
      --query "instanceView.statuses[?starts_with(code,'PowerState/')].code | [0]" -o tsv 2>/dev/null | sed 's#PowerState/##' || echo "")"
  fi

  # Billable + infra inventories.
  local ip_json disk_json ip_rows disk_rows nic_n vnet_n nip ndisk
  ip_json="$(az network public-ip list -g "$rg" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" -o json 2>/dev/null || echo "[]")"
  disk_json="$(az disk list -g "$rg" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" -o json 2>/dev/null || echo "[]")"
  ip_rows="$(printf '%s' "$ip_json" | ip_rows_from_json)"
  disk_rows="$(printf '%s' "$disk_json" | disk_rows_from_json)"
  nic_n="$(az network nic list -g "$rg" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" --query "length(@)" -o tsv 2>/dev/null || echo 0)"
  vnet_n="$(az network vnet list -g "$rg" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" --query "length(@)" -o tsv 2>/dev/null || echo 0)"
  [[ "$nic_n"  =~ ^[0-9]+$ ]] || nic_n=0
  [[ "$vnet_n" =~ ^[0-9]+$ ]] || vnet_n=0

  # Count IPs + accrue their standing cost (shared helper).
  nip=0
  local ipname ipsku ipalloc ipattach iploc m
  while IFS=$'\t' read -r ipname ipsku ipalloc ipattach iploc; do
    [[ -z "$ipname" ]] && continue
    nip=$((nip+1))
    [[ "$region" == "?" || -z "$region" ]] && region="$iploc"
    m="$(ip_row_monthly "$ipsku" "$ipalloc" "$ipattach" "$iploc")"
    [[ -n "$m" ]] && standing="$(awk -v a="$standing" -v b="$m" 'BEGIN{printf "%.2f", a+b}')"
  done <<<"$ip_rows"

  # Count disks + accrue their standing cost (shared helper).
  ndisk=0
  local dname dsku dsize dloc dattach priced dmon dtsku
  while IFS=$'\t' read -r dname dsku dsize dloc dattach; do
    [[ -z "$dname" ]] && continue
    ndisk=$((ndisk+1))
    priced="$(disk_row_monthly "$dsku" "$dsize" "$dloc")"
    if [[ -n "$priced" ]]; then
      IFS=$'\t' read -r dmon dtsku <<<"$priced"
      standing="$(awk -v a="$standing" -v b="$dmon" 'BEGIN{printf "%.2f", a+b}')"
    fi
  done <<<"$disk_rows"

  # Short resource summary.
  local toks=""
  [[ -n "$vmname" ]] && toks="vm"
  if [[ "$nip"   -gt 0 ]]; then toks="${toks:+$toks, }ip";   [[ "$nip"   -gt 1 ]] && toks="${toks}x${nip}"; fi
  if [[ "$ndisk" -gt 0 ]]; then toks="${toks:+$toks, }disk"; [[ "$ndisk" -gt 1 ]] && toks="${toks}x${ndisk}"; fi
  [[ "$nic_n"  -gt 0 ]] && toks="${toks:+$toks, }nic"
  [[ "$vnet_n" -gt 0 ]] && toks="${toks:+$toks, }vnet"
  [[ -z "$toks" ]] && toks="none"
  resources="$toks"

  # Status classification (power is the bare PowerState value, e.g. "running").
  if [[ -n "$vmname" ]]; then
    case "$power" in
      running)             status="running" ;;
      deallocated|stopped) status="stopped" ;;
      *)                   status="stopped" ;;
    esac
  elif [[ "$nip" -gt 0 || "$ndisk" -gt 0 || "$nic_n" -gt 0 || "$vnet_n" -gt 0 ]]; then
    status="partial"
  else
    status="empty"
  fi

  printf '%s\t%s\t%s\t%s\t%s\n' "$name" "$region" "$status" "$resources" "$standing"
}

# --- Compact inventory table (--list) --------------------------------------
# One row per discovered Azure instance, with status, resource summary, and
# standing monthly cost; plus a combined total. Read-only, Azure-discovery based.
run_list() {
  local names name total="0" count=0 sub_name
  sub_name="$(az account show "${SUB_OPT[@]+"${SUB_OPT[@]}"}" --query name -o tsv 2>/dev/null || echo '?')"
  names="$(discover_instances)"

  echo "==============================================================="
  echo " A100 GPU dev VMs - inventory   ($(date '+%Y-%m-%d %H:%M:%S'))"
  printf " Subscription   : %s\n" "$sub_name"
  echo "==============================================================="
  if [[ -z "$names" ]]; then
    c_warn " No instances found in Azure (subscription ${sub_name})."; echo
    echo "==============================================================="
    return 0
  fi

  printf " %-22s %-18s %-9s %-24s %12s\n" "INSTANCE" "REGION" "STATUS" "RESOURCES" "STANDING \$/mo"
  printf " %-22s %-18s %-9s %-24s %12s\n" "----------------------" "------------------" "---------" "------------------------" "------------"

  local inst region status resources standing rec
  while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    rec="$(inventory_row "$name")"
    IFS=$'\t' read -r inst region status resources standing <<<"$rec"
    count=$((count+1))
    total="$(awk -v a="$total" -v b="$standing" 'BEGIN{printf "%.2f", a+b}')"
    printf " %-22s %-18s " "$inst" "$region"
    case "$status" in
      running) c_ok   "$(printf '%-9s' running)" ;;
      stopped) c_warn "$(printf '%-9s' stopped)" ;;
      partial) c_err  "$(printf '%-9s' partial)" ;;
      *)       c_warn "$(printf '%-9s' empty)"   ;;
    esac
    printf " %-24s %12s\n" "$resources" "\$${standing}"
  done <<<"$names"

  echo "==============================================================="
  printf " Instances: %s    Combined standing: " "$count"
  c_ok "\$${total}"; printf " /mo (bills 24/7)\n"
  c_warn " partial = resources exist but no VM (incomplete/failed provision still billing)."; echo
  echo "==============================================================="
  return 0
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
  DASH_STANDING="0"   # this instance's monthly standing cost (for --all totals).
  resolve_rg

  echo "==============================================================="
  echo " A100 GPU dev VMs   ($(date '+%Y-%m-%d %H:%M:%S'))"
  local sub_name
  sub_name="$(az account show "${SUB_OPT[@]+"${SUB_OPT[@]}"}" --query name -o tsv 2>/dev/null || echo '?')"
  printf " Instance       : %s\n" "$INSTANCE"
  printf " Subscription   : %s\n" "$sub_name"
  printf " Resource group : %s\n" "$RG"
  echo "==============================================================="

  # If the resource group does not exist at all, there is nothing billable.
  local rg_exists
  rg_exists="$(az group exists -g "$RG" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" 2>/dev/null || echo "false")"
  if [[ "$rg_exists" != "true" ]]; then
    c_warn " Instance '${INSTANCE}': resource group '${RG}' does not exist."; echo
    printf " Standing resources: "; c_ok "\$0"; printf " (no resource group)\n"
    echo " (Provision it with: scripts/provision.sh --name ${INSTANCE})"
    echo "==============================================================="
    return
  fi

  # Enumerate VMs in the resource group.
  local vms
  vms="$(az vm list -g "$RG" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" --query "[].name" -o tsv 2>/dev/null || echo "")"
  if [[ -z "$vms" ]]; then
    c_warn " Instance '${INSTANCE}': resource group '${RG}' exists but has no VM."; echo
    echo "---------------------------------------------------------------"
    standing_resources "$RG" "no"
    DASH_STANDING="$STANDING_SUBTOTAL"
    echo "==============================================================="
    printf " Standing monthly (this instance, billed 24/7): "; c_ok "\$${DASH_STANDING}"; echo
    c_warn " No VM here - compute cost is \$0, but the above resources still bill."; echo
    echo " (Provision a VM with: scripts/provision.sh --name ${INSTANCE})"
    echo "==============================================================="
    return
  fi

  local total_cost="0"
  local accruing="false"

  local vm
  while IFS= read -r vm; do
    [[ -z "$vm" ]] && continue

    # Core properties in a single call (array preserves order).
    local props size location prio created vmid admin
    props="$(az vm show -g "$RG" -n "$vm" "${SUB_OPT[@]+"${SUB_OPT[@]}"}" \
      --query "[hardwareProfile.vmSize, location, priority, timeCreated, id, osProfile.adminUsername]" -o tsv 2>/dev/null || echo "")"
    IFS=$'\t' read -r size location prio created vmid admin <<<"$props"
    [[ -z "${prio:-}" || "$prio" == "None" ]] && prio="Regular"
    [[ -z "${admin:-}" || "$admin" == "None" ]] && admin="azureuser"

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
      if ! ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
            "${admin}@${ip}" "nvidia-smi" 2>/dev/null; then
        c_warn " Could not run nvidia-smi (SSH key not loaded, or driver not ready)."; echo
      fi
    fi
  done <<<"$vms"

  # Expose this instance's accrued total so --all can sum across instances.
  DASH_SUBTOTAL="$total_cost"

  # Standing resources (IP + disk) for this RG: always billing, shown regardless
  # of VM power state.
  echo "---------------------------------------------------------------"
  standing_resources "$RG" "yes"
  DASH_STANDING="$STANDING_SUBTOTAL"

  echo "==============================================================="
  if [[ "$accruing" == "true" ]]; then
    printf " TOTAL accrued (running VMs, compute only): "; c_ok "\$${total_cost}"; echo
  else
    c_warn " No running VMs - compute not accruing right now."; echo
  fi
  printf " Standing monthly (this instance, billed 24/7): "; c_ok "\$${DASH_STANDING}"; echo
  c_warn " Compute = hourly accrual while running; standing = monthly IP + disk that bill 24/7."; echo
  echo "==============================================================="
}

# --- Inspect every instance discovered in Azure ----------------------------
# Discovers instances from Azure resource groups (NOT Terraform workspaces),
# prints a dashboard for each, then combined compute + standing totals. Handles
# the empty case gracefully and never aborts the loop on one bad instance.
run_all() {
  local names name grand="0" grand_standing="0" found="false"

  names="$(discover_instances)"

  if [[ -z "$names" ]]; then
    local sub_name
    sub_name="$(az account show "${SUB_OPT[@]+"${SUB_OPT[@]}"}" --query name -o tsv 2>/dev/null || echo '?')"
    echo "==============================================================="
    echo " A100 GPU dev VMs   ($(date '+%Y-%m-%d %H:%M:%S'))"
    echo "==============================================================="
    c_warn " No instances found in Azure (subscription ${sub_name})."; echo
    echo " Create one: scripts/provision.sh --name <name>"
    echo "==============================================================="
    return 0
  fi

  while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    INSTANCE="$name"
    RG_OVERRIDE=""        # always resolve each instance's own RG by name.
    dashboard
    grand="$(awk -v a="$grand" -v b="${DASH_SUBTOTAL:-0}" 'BEGIN{printf "%.2f", a+b}')"
    grand_standing="$(awk -v a="$grand_standing" -v b="${DASH_STANDING:-0}" 'BEGIN{printf "%.2f", a+b}')"
    found="true"
  done <<<"$names"

  echo "==============================================================="
  if [[ "$found" == "true" ]]; then
    printf " COMBINED accrued across all instances (compute only, hourly accrual): "
    c_ok "\$${grand}"; echo
    printf " COMBINED standing across all instances (monthly, bills 24/7):         "
    c_ok "\$${grand_standing}"; echo
  fi
  c_warn " Compute accrues only while VMs run; standing (IP + disk) bills 24/7. Spot prices vary."; echo
  echo "==============================================================="
  return 0
}

# Render once. --list -> compact inventory table; --name -> single instance;
# otherwise (default / --all) -> every Azure instance's full dashboard.
render() {
  if [[ "$DO_LIST" == "true" ]]; then
    run_list
  elif [[ "$NAME_SET" == "true" ]]; then
    dashboard
  else
    run_all
  fi
}

# --- Full-screen terminal handling -----------------------------------------
# Uses the alternate screen buffer so live mode owns the screen and never
# pollutes scrollback. tput where available, raw ANSI as a portable fallback.
ALT_ACTIVE="false"
enter_altscreen() {
  tput smcup 2>/dev/null || printf '\033[?1049h'
  tput civis 2>/dev/null || printf '\033[?25l'
  ALT_ACTIVE="true"
}
leave_altscreen() {
  [[ "$ALT_ACTIVE" == "true" ]] || return 0
  tput cnorm 2>/dev/null || printf '\033[?25h'
  tput rmcup 2>/dev/null || printf '\033[?1049l'
  ALT_ACTIVE="false"
}
clear_screen() {
  # Move home + clear to end of display so values redraw in place.
  { tput home && tput ed; } 2>/dev/null || printf '\033[H\033[2J'
}

# Monitor never touches Terraform state/workspaces. Cleanup restores the
# terminal (if live mode took it over) and removes the Retail Prices cache.
cleanup() {
  leave_altscreen
  if [[ -n "$PRICE_CACHE_DIR" && -d "$PRICE_CACHE_DIR" ]]; then
    rm -rf "$PRICE_CACHE_DIR" 2>/dev/null || true
  fi
}

# Full-screen live loop: redraw in place every interval until Ctrl-C / q.
live_loop() {
  local interval="$1"
  # No TTY (piped/redirected): a single plain render keeps output usable.
  if [[ ! -t 1 ]]; then
    render
    return
  fi
  enter_altscreen
  local key
  while true; do
    clear_screen
    printf " "; c_ok "LIVE"
    printf "  refresh %ss   %s   (press q or Ctrl-C to exit)\n" \
      "$interval" "$(date '+%Y-%m-%d %H:%M:%S')"
    render
    # Responsive wait: returns after <interval>s, or immediately on a keypress.
    key=""
    read -t "$interval" -r -n 1 key 2>/dev/null || true
    [[ "$key" == "q" || "$key" == "Q" ]] && break
  done
}

main() {
  check_prereqs
  cache_init
  # Restore terminal + clean cache on any exit path, including Ctrl-C / SIGTERM.
  trap cleanup EXIT
  trap 'cleanup; exit 130' INT
  trap 'cleanup; exit 143' TERM

  # --watch implies live mode; validate the interval if given.
  local interval=5
  if [[ -n "$WATCH_INTERVAL" ]]; then
    if ! [[ "$WATCH_INTERVAL" =~ ^[0-9]+$ ]] || [[ "$WATCH_INTERVAL" -lt 1 ]]; then
      log_err "--watch requires a positive integer number of seconds."; exit 2
    fi
    interval="$WATCH_INTERVAL"
  fi

  if [[ "$DO_TOP" == "true" ]]; then
    live_loop "$interval"
  else
    render
  fi
}

main "$@"
