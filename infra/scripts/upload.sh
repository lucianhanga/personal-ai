#!/usr/bin/env bash
#
# upload.sh - Copy one or more local files to a remote machine's /tmp folder.
#
# By default the target is an SSH destination: a host alias from ~/.ssh/config
# (HostName/User/IdentityFile/ports are resolved by ssh), a "user@host", or an
# IP. This is how you already reach the GPU VMs, so no Azure/Terraform is needed.
#
# With --tf, the host is instead resolved from this repo's Terraform outputs for
# the named workspace (the connect.sh flow); that requires `terraform init` and
# live state for that instance.
#
# Examples:
#   scripts/upload.sh -n vm-hochtief-a100-de ~/Desktop/shot.png   # -> /tmp/shot.png
#   scripts/upload.sh -n azure-private-gpu-vm a.txt b.txt          # both into /tmp
#   scripts/upload.sh -n vm-hochtief-a100-de -d /tmp/in data.zip   # -> /tmp/in/data.zip
#   scripts/upload.sh -n azureuser@52.166.93.27 -i ~/.ssh/key f    # explicit user/key
#   scripts/upload.sh --tf -n devel model.gguf                     # resolve via Terraform
#
set -euo pipefail

# --- Shared helpers --------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
TF_DIR="$(cd "${SCRIPT_DIR}/../terraform" 2>/dev/null && pwd || true)"

# --- Defaults --------------------------------------------------------------
HOST=""            # SSH destination (host alias, user@host, or IP), or TF workspace with --tf.
IDENTITY=""        # optional ssh key override (-i).
DEST_DIR="/tmp"    # remote destination directory.
SUBSCRIPTION=""    # optional az subscription (id or name); empty = CLI default.
USE_TF=0           # 1 = resolve host from Terraform outputs.
FILES=()

usage() {
  cat <<EOF
Usage: $(basename "$0") -n <host> [options] <local-file> [more-files...]

Copy one or more local files to a remote machine (default destination: /tmp).

Required:
  -n, --host <dest>       SSH destination: a ~/.ssh/config host alias, user@host,
                          or IP. With --tf, this is a Terraform workspace name.

Options:
  -d, --dest <dir>        Remote destination directory. Default: /tmp.
  -i, --identity <path>   Private key to authenticate with (scp -i). Usually not
                          needed if your ~/.ssh/config sets IdentityFile.
  -s, --subscription <id|name>  Azure subscription used when -n is a bare instance
                          name resolved via Azure. Default: CLI default.
      --tf                Resolve the host from Terraform outputs (connect.sh flow)
                          instead of treating -n as an SSH destination.
  -h, --help              Show this help.
EOF
}

# --- Parse args ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--host|--name|--instance) HOST="${2:-}"; shift 2 ;;
    -d|--dest) DEST_DIR="${2:-}"; shift 2 ;;
    -i|--identity) IDENTITY="${2:-}"; shift 2 ;;
    -s|--subscription) SUBSCRIPTION="${2:-}"; shift 2 ;;
    --tf) USE_TF=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; FILES+=("$@"); break ;;
    -*) log_err "Unknown option: $1"; usage; exit 2 ;;
    *) FILES+=("$1"); shift ;;
  esac
done

[[ -z "$HOST" ]] && { log_err "A target host is required (-n <host>)."; usage; exit 2; }
[[ -z "$DEST_DIR" ]] && { log_err "--dest requires a non-empty value."; exit 2; }

if [[ ${#FILES[@]} -eq 0 ]]; then
  log_err "No local file given to upload."
  usage
  exit 2
fi

# --- Validate local files ---------------------------------------------------
for f in "${FILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    log_err "Local file not found: $f"; exit 2
  fi
done

if ! command -v scp >/dev/null 2>&1; then
  log_err "Required tool not found: scp"; exit 3
fi

# --- Resolve the SSH destination -------------------------------------------
if [[ "$USE_TF" -eq 1 ]]; then
  # Terraform flow: -n names a workspace; read host/user from outputs.
  for tool in az terraform; do
    command -v "$tool" >/dev/null 2>&1 || { log_err "Required tool not found: $tool"; exit 3; }
  done
  [[ -d "$TF_DIR" ]] || { log_err "Terraform dir not found next to scripts/ (../terraform)."; exit 5; }

  cd "$TF_DIR"
  if [[ ! -d .terraform ]]; then
    log_err "Terraform is not initialized in ${TF_DIR}. Run: (cd infra/terraform && terraform init)"
    exit 5
  fi
  # Select the workspace; surface the real error instead of dying silently.
  if ! terraform workspace select "$HOST" >/dev/null 2>&1; then
    log_err "Terraform workspace '${HOST}' does not exist. Available:"
    terraform workspace list >&2 || true
    exit 5
  fi
  ADMIN="$(terraform output -raw admin_username 2>/dev/null || echo "azureuser")"
  PUBIP="$(terraform output -raw public_ip_address 2>/dev/null || echo "")"
  [[ -z "$PUBIP" ]] && { log_err "No public_ip_address output for workspace '${HOST}'. Is it provisioned?"; exit 5; }
  SSH_DEST="${ADMIN}@${PUBIP}"
elif [[ "$HOST" == *@* || "$HOST" == *.* || "$HOST" == *:* ]] || grep -qiE "^[[:space:]]*Host[[:space:]]+([^#]*[[:space:]])?${HOST}([[:space:]]|$)" "${HOME}/.ssh/config" 2>/dev/null; then
  # Direct SSH flow: a user@host, an IP, or a ~/.ssh/config Host alias.
  # ssh/scp resolve HostName/User/IdentityFile/ports from ~/.ssh/config.
  SSH_DEST="$HOST"
else
  # Bare instance name (e.g. "germanywestcentralvm"): resolve the VM's public IP
  # from Azure via the shared resolver (RG-scoped + subscription-scoped).
  if ! command -v az >/dev/null 2>&1; then
    log_err "'${HOST}' is not an SSH host/IP and Azure CLI is unavailable to resolve it."
    log_err "Pass a reachable target (user@host or ~/.ssh/config alias), or install az + run: az login"
    exit 5
  fi
  log_ok "Resolving instance '${HOST}' via Azure ..."
  require_az_login
  resolve_instance "$HOST"
  SSH_DEST="${ADMIN}@${PUBIP}"
  # Default to the dedicated project key if the caller did not pass -i.
  [[ -z "$IDENTITY" && -f "$DEFAULT_KEY" ]] && IDENTITY="$DEFAULT_KEY"
  log_ok "Resolved '${HOST}' -> ${SSH_DEST}"
fi

# --- Common ssh/scp options -------------------------------------------------
SSH_OPTS=("${SSH_BASE_OPTS[@]}")
[[ -n "$IDENTITY" ]] && SSH_OPTS+=(-i "$IDENTITY")

# --- Connectivity check (loud) ---------------------------------------------
ERRF="$(mktemp)"
trap 'rm -f "$ERRF"' EXIT
if ! ssh "${SSH_OPTS[@]}" -o BatchMode=yes "$SSH_DEST" true 2>"$ERRF"; then
  log_err "Cannot SSH to '${SSH_DEST}'."
  sed 's/^/       /' "$ERRF" >&2 2>/dev/null || true
  log_err "Check the host alias in ~/.ssh/config, or pass -i <key>."
  exit 7
fi

# --- Ensure the remote destination directory exists ------------------------
if ! ssh "${SSH_OPTS[@]}" "$SSH_DEST" "mkdir -p $(printf '%q' "$DEST_DIR")"; then
  log_err "Could not create remote directory: ${DEST_DIR}"
  exit 7
fi

# --- Upload -----------------------------------------------------------------
log_ok "Uploading ${#FILES[@]} file(s) to ${SSH_DEST}:${DEST_DIR}/ ..."
if ! scp "${SSH_OPTS[@]}" "${FILES[@]}" "${SSH_DEST}:${DEST_DIR}/"; then
  log_err "Upload failed."
  exit 8
fi

# --- Verify and report ------------------------------------------------------
for f in "${FILES[@]}"; do
  base="$(basename "$f")"
  if ssh "${SSH_OPTS[@]}" "$SSH_DEST" "test -f $(printf '%q' "${DEST_DIR}/${base}")"; then
    log_ok "Uploaded: ${base} -> ${DEST_DIR}/${base}"
  else
    log_warn "Could not verify ${DEST_DIR}/${base} on the remote."
  fi
done
