#!/usr/bin/env bash
#
# setup-devtools.sh - Idempotent developer toolchain installer for the A100 dev
# VM (Ubuntu / NVIDIA NGC image). Installs the toolchains required by doktokNG
# and personalAI. TOOLS ONLY - it does not clone the project repositories.
#
# Safe to re-run. Runs on first boot via Terraform cloud-init (custom_data), or
# manually:  sudo TARGET_USER=azureuser bash setup-devtools.sh
#
# Installs (after an apt update + upgrade):
#   - base build libs + native deps (libpq, libmagic, libGL, libgomp, ...)
#   - nvtop (GPU top)
#   - git + GitHub CLI (gh)
#   - Docker + compose v2
#   - uv + Python 3.12
#   - Node.js 22 + pnpm 11.5.1
#   - Claude Code CLI (@anthropic-ai/claude-code)
#   - Ollama (uses the A100 GPU automatically)
#   - pre-pulls the shared Ollama models (qwen3-embedding:0.6b, qwen3.6:35b-a3b)
#
# Env:
#   TARGET_USER     user that owns per-user installs (default: azureuser)
#   PREPULL_MODELS  "true"/"false" - pre-pull Ollama models (default: true)
#
# Best-effort: a single failing optional step logs a warning and continues.
#
set -uo pipefail

TARGET_USER="${TARGET_USER:-azureuser}"
PREPULL_MODELS="${PREPULL_MODELS:-true}"
MARKER="/var/lib/devtools-setup.done"
export DEBIAN_FRONTEND=noninteractive

log()  { printf '[devtools %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
warn() { printf '[devtools %s] WARN: %s\n' "$(date -u +%H:%M:%S)" "$*"; }
run_as_user() { sudo -u "$TARGET_USER" -H bash -lc "$*"; }

if [[ "$(id -u)" -ne 0 ]]; then
  echo "This script must run as root (use sudo)."; exit 1
fi

log "Starting toolchain setup for user '${TARGET_USER}' (prepull_models=${PREPULL_MODELS})."

# 1) Base system: update, upgrade, then install packages ----------------------
log "Updating apt package index..."
apt-get update -y || warn "apt-get update failed"
log "Upgrading installed packages (apt-get upgrade)..."
apt-get upgrade -y || warn "apt-get upgrade failed"
log "Installing base apt packages..."
# nvtop = an interactive GPU 'top' for NVIDIA (live GPU/VRAM/process view).
apt-get install -y --no-install-recommends \
  git curl ca-certificates gnupg lsb-release unzip jq make \
  build-essential python3-dev pkg-config \
  libssl-dev libffi-dev libpq-dev \
  libmagic1 libgl1 libglib2.0-0 libgomp1 \
  postgresql-client nvtop || warn "some base packages failed to install"

# 2) GitHub CLI (gh) ----------------------------------------------------------
if ! command -v gh >/dev/null 2>&1; then
  log "Installing GitHub CLI (gh)..."
  mkdir -p -m 755 /etc/apt/keyrings
  if curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
       -o /etc/apt/keyrings/githubcli-archive-keyring.gpg; then
    chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list
    apt-get update -y && apt-get install -y gh || warn "gh install failed"
  else
    warn "could not fetch gh keyring"
  fi
fi

# 3) Docker + compose v2 ------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  log "Installing Docker..."
  curl -fsSL https://get.docker.com | sh || warn "docker install failed"
fi
if command -v docker >/dev/null 2>&1; then
  systemctl enable --now docker 2>/dev/null || true
  usermod -aG docker "$TARGET_USER" 2>/dev/null || true
fi

# 4) uv + Python 3.12 (per target user) --------------------------------------
if ! run_as_user 'command -v uv >/dev/null 2>&1'; then
  log "Installing uv for ${TARGET_USER}..."
  run_as_user 'curl -LsSf https://astral.sh/uv/install.sh | sh' || warn "uv install failed"
fi
run_as_user 'export PATH="$HOME/.local/bin:$PATH"; uv python install 3.12' \
  || warn "uv python 3.12 install failed"

# 5) Node.js 22 + pnpm 11.5.1 -------------------------------------------------
NODE_MAJOR="$(node -v 2>/dev/null | grep -oE '^v[0-9]+' || true)"
if [[ "$NODE_MAJOR" != "v22" ]]; then
  log "Installing Node.js 22..."
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash - || warn "nodesource setup failed"
  apt-get install -y nodejs || warn "node install failed"
fi
if command -v npm >/dev/null 2>&1 && ! command -v pnpm >/dev/null 2>&1; then
  log "Installing pnpm 11.5.1..."
  npm install -g pnpm@11.5.1 || warn "pnpm install failed"
fi

# 5b) Claude Code CLI (Anthropic, native installer) --------------------------
# The native installer is more reliable than the npm package (which can ship a
# broken bin symlink). Installs per-user to ~/.local/bin.
if ! run_as_user '[ -x "$HOME/.local/bin/claude" ]'; then
  log "Installing Claude Code CLI (native) for ${TARGET_USER}..."
  run_as_user 'curl -fsSL https://claude.ai/install.sh | bash' || warn "claude code install failed"
fi
# Ensure ~/.local/bin is on PATH for future login shells.
run_as_user 'grep -qs ".local/bin" "$HOME/.bashrc" || printf "\nexport PATH=\"\$HOME/.local/bin:\$PATH\"\n" >> "$HOME/.bashrc"' \
  || warn "could not update PATH in .bashrc"

# 6) Ollama (GPU auto-detected on the NGC image) -----------------------------
if ! command -v ollama >/dev/null 2>&1; then
  log "Installing Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh || warn "ollama install failed"
fi
# A100 tuning: allow some parallelism + a couple of loaded models.
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/override.conf <<'EOF'
[Service]
Environment="OLLAMA_NUM_PARALLEL=4"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
EOF
systemctl daemon-reload 2>/dev/null || true
systemctl enable --now ollama 2>/dev/null || true

# 7) Pre-pull the shared Ollama models ---------------------------------------
if [[ "$PREPULL_MODELS" == "true" ]] && command -v ollama >/dev/null 2>&1; then
  log "Waiting for the Ollama daemon..."
  for _ in $(seq 1 30); do ollama list >/dev/null 2>&1 && break; sleep 2; done
  for m in qwen3-embedding:0.6b qwen3.6:35b-a3b; do
    log "Pulling Ollama model: ${m} (this can take a while)..."
    ollama pull "$m" || warn "failed to pull ${m}"
  done
fi

# 8) Done ---------------------------------------------------------------------
{
  echo "completed_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "node=$(node -v 2>/dev/null || echo n/a)"
  echo "pnpm=$(pnpm -v 2>/dev/null || echo n/a)"
  echo "uv=$(run_as_user 'export PATH=$HOME/.local/bin:$PATH; uv --version' 2>/dev/null || echo n/a)"
  echo "docker=$(docker --version 2>/dev/null || echo n/a)"
  echo "ollama=$(ollama --version 2>/dev/null || echo n/a)"
} > "$MARKER"

log "Developer toolchain setup complete. Summary written to ${MARKER}."
