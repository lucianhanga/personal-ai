#!/usr/bin/env bash
#
# sync-data.sh - Sync the personalAI (or doktokNG) Postgres database between THIS
# machine and a named A100 dev VM, over SSH.
#
# personalAI stores all its data (documents, embeddings, chats, memory) in
# PostgreSQL - not flat files - so this does a database dump/restore
# (pg_dump | pg_restore piped over SSH), NOT an rsync. The Postgres container
# (started by the project's `make db`) must be running on BOTH ends.
#
#   --push  (default)  local DB  -> remote DB   (replaces remote data)
#   --pull             remote DB -> local  DB   (replaces local data)
#
# WARNING: the destination database is overwritten (pg_restore --clean).
#
# Examples:
#   scripts/sync-data.sh --name germanywestcentralvm            # push local -> VM
#   scripts/sync-data.sh --name germanywestcentralvm --pull     # back up VM -> local
#   scripts/sync-data.sh --name germanywestcentralvm --db doktok --user doktok
#
set -euo pipefail

# --- Colors ----------------------------------------------------------------
if [[ -t 1 ]]; then
  GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'
else
  GREEN=''; RED=''; YELLOW=''; NC=''
fi
log_ok()   { printf "${GREEN}[ OK ]${NC} %s\n" "$*"; }
log_warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$*"; }
log_err()  { printf "${RED}[FAIL]${NC} %s\n" "$*" >&2; }
log_info() { printf "%s\n" "$*"; }

# --- Defaults --------------------------------------------------------------
INSTANCE="devel"
DIRECTION="push"
DBNAME="personalai"
DBUSER="personalai"
KEY="${HOME}/.ssh/ai-a100-devel"
ADMIN="azureuser"
HOST_OVERRIDE=""
SUBSCRIPTION=""
AUTO_APPROVE="false"
EXCLUDE_DOCS="false"  # --no-docs: sync config/chats/memory but NOT the document corpus + KAG
PG_MATCH="pgvector"   # substring matched against running container images

# Document-corpus + knowledge-graph tables whose DATA is skipped with --no-docs (schemas are still
# created, just left empty — re-ingest on the destination). No other table FK-references these, so a
# partial restore is consistent; embeddings/KAG are re-derived on ingest anyway (and must be if the
# embed model/dimension differs on the destination).
EXCLUDE_TABLES=(documents vectors entities entity_documents entity_edges folder_sources folder_files)

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Sync the project's Postgres database between this machine and a named VM.

Options:
  -n, --name <name>        Target instance (alias: --instance). Default: devel.
      --push               Local  -> remote (default). Replaces REMOTE data.
      --pull               Remote -> local.            Replaces LOCAL data.
      --db <name>          Database name (default: personalai).
      --user <name>        Database user (default: personalai).
      --no-docs            Sync everything EXCEPT the document corpus + knowledge graph
                           (documents, vectors, entities, folder sources) — re-ingest on the dest.
      --host <user@host>   Connect directly instead of resolving from --name.
  -i, --identity <path>    SSH private key (default: ~/.ssh/ai-a100-devel).
  -s, --subscription <id>  Azure subscription for IP lookup (default: CLI default).
  -y, --auto-approve       Skip the overwrite confirmation.
  -h, --help               Show this help.

The Postgres container (project's 'make db') must be running on both ends.
EOF
}

# --- Parse args ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--name|--instance) INSTANCE="${2:-}"; shift 2 ;;
    --push) DIRECTION="push"; shift ;;
    --pull) DIRECTION="pull"; shift ;;
    --db)   DBNAME="${2:-}"; shift 2 ;;
    --user) DBUSER="${2:-}"; shift 2 ;;
    --no-docs|--exclude-docs|--exclude-knowledge) EXCLUDE_DOCS="true"; shift ;;
    --host) HOST_OVERRIDE="${2:-}"; shift 2 ;;
    -i|--identity) KEY="${2:-}"; shift 2 ;;
    -s|--subscription) SUBSCRIPTION="${2:-}"; shift 2 ;;
    -y|--auto-approve) AUTO_APPROVE="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) log_err "Unknown argument: $1"; usage; exit 2 ;;
  esac
done

KEY="${KEY/#\~/$HOME}"

# --- Prerequisites ---------------------------------------------------------
for tool in ssh docker; do
  command -v "$tool" >/dev/null 2>&1 || { log_err "Required tool not found: $tool"; exit 3; }
done
[[ -f "$KEY" ]] || { log_err "SSH key not found: $KEY"; exit 3; }

# --- Resolve the remote host -----------------------------------------------
if [[ -n "$HOST_OVERRIDE" ]]; then
  REMOTE="$HOST_OVERRIDE"
else
  command -v az >/dev/null 2>&1 || { log_err "az not found (needed to resolve the VM IP)"; exit 3; }
  SUB_OPT=(); [[ -n "$SUBSCRIPTION" ]] && SUB_OPT=(--subscription "$SUBSCRIPTION")
  RG="ai-${INSTANCE}-a100-rg"
  PUBIP="$(az network public-ip show -g "$RG" -n "vm-ai-a100-${INSTANCE}-ip" \
            "${SUB_OPT[@]+"${SUB_OPT[@]}"}" --query ipAddress -o tsv 2>/dev/null || echo "")"
  [[ -z "$PUBIP" || "$PUBIP" == "None" ]] && { log_err "No public IP for instance '${INSTANCE}' (RG ${RG})."; exit 4; }
  REMOTE="${ADMIN}@${PUBIP}"
fi
SSH_CMD="ssh -i ${KEY} -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"

# --- Locate the Postgres containers ----------------------------------------
# The user may run several Postgres containers (e.g. doktok-db AND personalai-db),
# so pick the one that actually serves DBUSER/DBNAME, not just any pgvector image.
find_local_pg() {
  local c
  for c in $(docker ps --format '{{.ID}} {{.Image}}' 2>/dev/null | awk '/pgvector|postgres/{print $1}'); do
    docker exec "$c" psql -U "$DBUSER" -d "$DBNAME" -tAc 'select 1' >/dev/null 2>&1 && { echo "$c"; return 0; }
  done
  return 1
}
LCID="$(find_local_pg || true)"
RCID="$($SSH_CMD "$REMOTE" "for c in \$(docker ps --format '{{.ID}} {{.Image}}' 2>/dev/null | awk '/pgvector|postgres/{print \$1}'); do docker exec \$c psql -U ${DBUSER} -d ${DBNAME} -tAc 'select 1' >/dev/null 2>&1 && { echo \$c; break; }; done" 2>/dev/null || echo "")"

log_info "Target    : ${REMOTE}"
log_info "Direction : ${DIRECTION}   DB: ${DBNAME} (user ${DBUSER})"
log_info "Local PG  : ${LCID:-<not running>}    Remote PG: ${RCID:-<not running>}"
[[ "$EXCLUDE_DOCS" == "true" ]] && log_warn "Excluding document corpus + knowledge graph data (${EXCLUDE_TABLES[*]}) — re-ingest on the destination."

need_local()  { [[ -n "$LCID" ]] || { log_err "Local Postgres container not running. Start it: (in the project) make db"; exit 5; }; }
need_remote() { [[ -n "$RCID" ]] || { log_err "Remote Postgres container not running on ${INSTANCE}. Start it on the VM: make db"; exit 5; }; }

confirm() {
  [[ "$AUTO_APPROVE" == "true" ]] && return 0
  printf "${YELLOW}%s [y/N]: ${NC}" "$1"; read -r r; [[ "$r" =~ ^[Yy]$ ]]
}

# --- Do the dump | restore -------------------------------------------------
# --no-docs: keep the table schemas but skip their DATA, so the destination gets every config/chat/
# memory row and EMPTY document/knowledge tables (re-ingest there). pg_restore --clean still drops &
# recreates those tables, so any stale docs/KAG already on the destination are cleared.
EXCLUDES=""
if [[ "$EXCLUDE_DOCS" == "true" ]]; then
  for t in "${EXCLUDE_TABLES[@]}"; do EXCLUDES+=" --exclude-table-data=${t}"; done
fi
DUMP="pg_dump -U ${DBUSER} -Fc -d ${DBNAME}${EXCLUDES}"
RESTORE="pg_restore -U ${DBUSER} -d ${DBNAME} --clean --if-exists --no-owner"

if [[ "$DIRECTION" == "push" ]]; then
  need_local; need_remote
  printf "${RED}This REPLACES the database '%s' on the VM (%s) with your local data.${NC}\n" "$DBNAME" "$INSTANCE"
  confirm "Proceed with push?" || { log_warn "Aborted."; exit 0; }
  log_info "Dumping local DB and restoring on the VM..."
  docker exec -i "$LCID" $DUMP | $SSH_CMD "$REMOTE" "docker exec -i ${RCID} ${RESTORE}"
  log_ok "Pushed local '${DBNAME}' -> VM '${INSTANCE}'."
else
  need_local; need_remote
  printf "${RED}This REPLACES your LOCAL database '%s' with the VM's data.${NC}\n" "$DBNAME"
  confirm "Proceed with pull?" || { log_warn "Aborted."; exit 0; }
  log_info "Dumping VM DB and restoring locally..."
  $SSH_CMD "$REMOTE" "docker exec -i ${RCID} ${DUMP}" | docker exec -i "$LCID" $RESTORE
  log_ok "Pulled VM '${INSTANCE}' -> local '${DBNAME}'."
fi
