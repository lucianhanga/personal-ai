#!/usr/bin/env bash
#
# sync-claude.sh - Sync Claude Code config + project memory between THIS machine
# and a named A100 dev VM, over SSH using the dedicated key.
#
# Syncs (both directions):
#   - ~/.claude/agents/        agent definitions
#   - ~/.claude/agent-memory/  user-level agent memories
#   - ~/.claude/CLAUDE.md      global preferences
#   - per --project: ~/.claude/projects/<key>/memory/   project memory
#
# Project-key gotcha: a project's memory lives under a key derived from its
# ABSOLUTE path (slashes -> dashes). That path differs between local and remote
# (e.g. local /Users/you/lgit/personalAI vs remote /home/azureuser/lgit/personal-ai),
# so project memory is mapped from the local key to the remote key. The remote
# project key directory is created if missing.
#
# Examples:
#   scripts/sync-claude.sh --name germanywestcentralvm                 # push global config
#   scripts/sync-claude.sh --name germanywestcentralvm --pull          # pull it back
#   scripts/sync-claude.sh --name germanywestcentralvm \
#     --project /Users/you/lgit/personalAI:/home/azureuser/lgit/personal-ai
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
DIRECTION="push"          # push (local -> remote) | pull (remote -> local)
DRY=""
SUBSCRIPTION=""
KEY="${HOME}/.ssh/ai-a100-devel"
ADMIN="azureuser"
PROJECTS=()
HOST_OVERRIDE=""

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Sync Claude Code config + project memory between this machine and a named VM.

Options:
  -n, --name <name>        Target instance (alias: --instance). Default: devel.
      --push               Local  -> remote (default).
      --pull               Remote -> local.
      --project <L[:R]>    Also sync this project's memory. L = local project path;
                           R = remote project path (default: \$REMOTE_HOME/lgit/<basename L>).
                           Repeatable.
      --host <user@host>   Connect to this host directly instead of resolving from --name.
  -i, --identity <path>    SSH private key (default: ~/.ssh/ai-a100-devel).
  -s, --subscription <id>  Azure subscription for IP lookup (default: CLI default).
      --dry-run            Show what rsync would do, change nothing.
  -h, --help               Show this help.
EOF
}

# --- Parse args ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--name|--instance) INSTANCE="${2:-}"; shift 2 ;;
    --push) DIRECTION="push"; shift ;;
    --pull) DIRECTION="pull"; shift ;;
    --project) PROJECTS+=("${2:-}"); shift 2 ;;
    --host) HOST_OVERRIDE="${2:-}"; shift 2 ;;
    -i|--identity) KEY="${2:-}"; shift 2 ;;
    -s|--subscription) SUBSCRIPTION="${2:-}"; shift 2 ;;
    --dry-run) DRY="-n"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) log_err "Unknown argument: $1"; usage; exit 2 ;;
  esac
done

KEY="${KEY/#\~/$HOME}"   # expand a leading ~

# --- Prerequisites ---------------------------------------------------------
for tool in rsync ssh; do
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
  [[ -z "$PUBIP" || "$PUBIP" == "None" ]] && { log_err "Could not find public IP for instance '${INSTANCE}' (RG ${RG})."; exit 4; }
  REMOTE="${ADMIN}@${PUBIP}"
fi

SSH_CMD="ssh -i ${KEY} -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
log_info "Target   : ${REMOTE}"
log_info "Direction: ${DIRECTION}  ${DRY:+(dry-run)}"

# Remote home (for absolute paths).
RHOME="$($SSH_CMD "$REMOTE" 'echo $HOME' 2>/dev/null || echo "")"
[[ -z "$RHOME" ]] && { log_err "Cannot SSH to ${REMOTE} with key ${KEY}."; exit 4; }
$SSH_CMD "$REMOTE" "mkdir -p '${RHOME}/.claude/agents' '${RHOME}/.claude/agent-memory' '${RHOME}/.claude/projects'" 2>/dev/null || true

# --- rsync helper ----------------------------------------------------------
# sync_path <local-abs> <remote-abs>   (direction-aware; trailing slash matters)
sync_path() {
  local lpath="$1" rpath="$2"
  if [[ "$DIRECTION" == "push" ]]; then
    [[ -e "${lpath%/}" ]] || { log_warn "skip (local missing): ${lpath}"; return; }
    rsync -a $DRY -e "$SSH_CMD" "$lpath" "${REMOTE}:${rpath}"
  else
    mkdir -p "$(dirname "${lpath%/}")"
    rsync -a $DRY -e "$SSH_CMD" "${REMOTE}:${rpath}" "$lpath"
  fi
  log_ok "synced ${DIRECTION}: ${lpath} <-> ${rpath}"
}

key_of() { printf '%s' "$1" | sed 's#/#-#g'; }   # /a/b -> -a-b

# --- 1) Global config ------------------------------------------------------
sync_path "${HOME}/.claude/agents/"       "${RHOME}/.claude/agents/"
sync_path "${HOME}/.claude/agent-memory/" "${RHOME}/.claude/agent-memory/"
sync_path "${HOME}/.claude/CLAUDE.md"     "${RHOME}/.claude/CLAUDE.md"

# --- 2) Project memory -----------------------------------------------------
for spec in ${PROJECTS[@]+"${PROJECTS[@]}"}; do
  lproj="${spec%%:*}"
  if [[ "$spec" == *:* ]]; then rproj="${spec#*:}"; else rproj="${RHOME}/lgit/$(basename "$lproj")"; fi
  # normalize local path to absolute if it exists
  [[ -d "$lproj" ]] && lproj="$(cd "$lproj" && pwd)"
  lkey="$(key_of "$lproj")"; rkey="$(key_of "$rproj")"
  lmem="${HOME}/.claude/projects/${lkey}/memory/"
  rmem="${RHOME}/.claude/projects/${rkey}/memory/"
  log_info "Project memory: ${lproj}  ->  ${rproj}"
  if [[ "$DIRECTION" == "push" ]]; then
    $SSH_CMD "$REMOTE" "mkdir -p '${rmem}'" 2>/dev/null || true
  else
    mkdir -p "$lmem"
  fi
  sync_path "$lmem" "$rmem"
done

log_ok "Claude sync complete (${DIRECTION})."
