#!/usr/bin/env bash
# PersonalAI one-command "semi-development" bootstrap.
#
# Takes a fresh clone to a running stack with a single command: it checks the required system
# tooling (with versions), installs the repo-local dependencies (Python via uv, JS via pnpm),
# brings up the local Postgres+pgvector container, waits for it to be healthy, then runs the
# backend and the UI together with prefixed/colored logs and a clean Ctrl-C shutdown.
#
# It is a developer-experience / onboarding convenience -- NOT a production deployment path.
# It complements (does not replace) the `make` targets and reuses them (make db, make setup, ...).
#
# Usage:
#   scripts/bootstrap.sh            # set up everything and run db -> backend -> UI
#   scripts/bootstrap.sh --no-run   # set up only (deps + db up), do not launch backend/UI
#   scripts/bootstrap.sh --help     # show this help
#   make dev                        # convenience wrapper for `scripts/bootstrap.sh`
#
# Platforms: macOS and Linux. Native Windows is out of scope; use WSL2 (it behaves like Linux).
#
# Security notes (see issue #401, docs/architecture/THREAT-MODEL.md):
#   - No `sudo`, no system package installs, no `curl | sh`. System tools are detected and the
#     user is pointed at the in-repo docs; only repo-local artifacts are installed
#     (.venv via uv, node_modules via pnpm, a local Docker container).
#   - Never prints `.env` contents or any PERSONALAI_* secret value; points to .env.example.
#   - Loopback binds and egress-off defaults are preserved; this script does not change them.
set -euo pipefail

# --- Bash version guard ------------------------------------------------------------------------
# This script uses `wait -n` (bash >= 4.3). macOS ships bash 3.2 as /bin/bash; the shebang and the
# `make dev` wrapper invoke `bash`, so a modern bash on PATH (e.g. Homebrew) is required. Fail with
# a clear message rather than misbehaving.
if [ -z "${BASH_VERSINFO:-}" ] || [ "${BASH_VERSINFO[0]}" -lt 4 ] \
   || { [ "${BASH_VERSINFO[0]}" -eq 4 ] && [ "${BASH_VERSINFO[1]}" -lt 3 ]; }; then
  printf '%s\n' "[FAIL] This script needs bash >= 4.3 (found ${BASH_VERSION:-unknown})." >&2
  printf '%s\n' "       macOS ships bash 3.2; install a newer bash (e.g. 'brew install bash')" >&2
  printf '%s\n' "       and run it with that bash, or via 'make dev' after it is on PATH." >&2
  exit 1
fi

# --- Colors (green=ok, amber/yellow=warn, red=fail; no emoji) ----------------------------------
# Honor NO_COLOR and non-tty output by disabling escapes.
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'
  BLUE=$'\033[0;34m'; CYAN=$'\033[0;36m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
  GREEN=''; YELLOW=''; RED=''; BLUE=''; CYAN=''; BOLD=''; RESET=''
fi

# --- Repo doc paths the messages link to (verified to exist before printing) -------------------
DOC_TOOLCHAIN="docs/development/toolchain.md"
DOC_LOCAL_CHAT="docs/guides/local-chat.md"
DOC_README="README.md (Quickstart)"

# --- Logging helpers ---------------------------------------------------------------------------
ok()    { printf '%s\n' "${GREEN}[ OK ]${RESET} $*"; }
warn()  { printf '%s\n' "${YELLOW}[WARN]${RESET} $*"; }
fail()  { printf '%s\n' "${RED}[FAIL]${RESET} $*" >&2; }
info()  { printf '%s\n' "${CYAN}[ .. ]${RESET} $*"; }
step()  { printf '\n%s\n' "${BOLD}== $* ==${RESET}"; }

usage() {
  cat <<'EOF'
PersonalAI bootstrap -- one command from a fresh clone to a running stack.

Usage:
  scripts/bootstrap.sh [options]

Options:
  --no-run        Set up dependencies and start the database, but do NOT launch
                  the backend or the UI (useful for CI-style preparation).
  -h, --help      Show this help and exit.

What it does (idempotent -- safe to re-run):
  1. Checks required system tools (uv, pnpm, node, docker + compose) and their
     versions. Missing/old ones fail fast with a link to the in-repo doc.
     Ollama is a soft dependency: if it is unreachable you get a WARNING, not a
     failure (the UI runs; chat needs a model).
  2. Installs repo-local deps: `uv sync` (Python) and `pnpm install` (JS).
  3. Starts local Postgres+pgvector (`make db`) and waits for it to be healthy.
     No migration step -- the backend self-applies migrations on startup.
  4. Runs the backend (127.0.0.1:8765) and the UI (http://localhost:5173)
     together, with [backend]/[ui] colored log prefixes. Ctrl-C stops both
     cleanly; the database container is left running (stop it with `make db-down`).

Platforms: macOS and Linux. On Windows use WSL2.
EOF
}

# --- Version helpers ---------------------------------------------------------------------------
# Compare two dotted versions. Returns 0 if $1 >= $2, 1 otherwise. Pure-shell, no external sort -V
# dependency (sort -V is missing on some BSD/macOS setups).
version_ge() {
  local have="$1" want="$2"
  # Strip any leading non-digits (e.g. "v20.1.0" -> "20.1.0").
  have="${have#v}"; want="${want#v}"
  local IFS=.
  # shellcheck disable=SC2206  # intentional word-split on '.' into version components
  local -a h=($have) w=($want)
  local i hi wi
  for i in 0 1 2; do
    hi="${h[i]:-0}"; wi="${w[i]:-0}"
    # Keep only the leading numeric run of each component (e.g. "1rc2" -> "1").
    hi="${hi%%[!0-9]*}"; wi="${wi%%[!0-9]*}"
    hi="${hi:-0}"; wi="${wi:-0}"
    if ((10#$hi > 10#$wi)); then return 0; fi
    if ((10#$hi < 10#$wi)); then return 1; fi
  done
  return 0
}

# --- Dependency checks -------------------------------------------------------------------------
# Each required check appends an actionable line to MISSING and flips DEPS_OK on failure.
DEPS_OK=1
note_missing() {
  DEPS_OK=0
  fail "$1"
}

check_uv() {
  if ! command -v uv >/dev/null 2>&1; then
    note_missing "uv not found -- the Python toolchain (Python 3.12) is required. Install it: ${DOC_TOOLCHAIN}"
    return
  fi
  local v
  v="$(uv --version 2>/dev/null | awk '{print $2}')"
  ok "uv ${v:-present} found"
}

check_node() {
  if ! command -v node >/dev/null 2>&1; then
    note_missing "node not found -- Node >=20 is required for the UI. Install it: ${DOC_TOOLCHAIN}"
    return
  fi
  local v
  v="$(node --version 2>/dev/null)"
  if version_ge "$v" "20.0.0"; then
    ok "node ${v} found (>=20)"
  else
    note_missing "node ${v} is too old -- need >=20. Upgrade: ${DOC_TOOLCHAIN}"
  fi
}

check_pnpm() {
  if ! command -v pnpm >/dev/null 2>&1; then
    note_missing "pnpm not found -- need >=11.5 (package.json pins pnpm@11.5.1). Install it: ${DOC_TOOLCHAIN}"
    return
  fi
  local v
  v="$(pnpm --version 2>/dev/null)"
  if version_ge "$v" "11.5.0"; then
    ok "pnpm ${v} found (>=11.5)"
  else
    note_missing "pnpm ${v} is too old -- need >=11.5. Upgrade: ${DOC_TOOLCHAIN}"
  fi
}

check_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    note_missing "docker not found -- needed for local Postgres+pgvector. Install it: ${DOC_LOCAL_CHAT}"
    return
  fi
  if ! docker compose version >/dev/null 2>&1; then
    note_missing "docker compose v2 not available (the 'docker compose' subcommand failed). Install/upgrade Docker: ${DOC_LOCAL_CHAT}"
    return
  fi
  if ! docker info >/dev/null 2>&1; then
    note_missing "the Docker daemon is not running or not reachable -- start Docker, then re-run. See ${DOC_LOCAL_CHAT}"
    return
  fi
  ok "docker + compose v2 found (daemon reachable)"
}

# Ollama is a SOFT dependency: warn (amber) and continue if it is unreachable or has no model.
OLLAMA_HOST_DEFAULT="http://127.0.0.1:11434"
check_ollama() {
  local host="${PERSONALAI_OLLAMA_HOST:-$OLLAMA_HOST_DEFAULT}"
  local tags
  if ! command -v curl >/dev/null 2>&1; then
    warn "curl not found -- skipping the Ollama reachability check. The UI still runs; chat needs Ollama. See ${DOC_LOCAL_CHAT}"
    return
  fi
  # 2s connect cap; do not fail the script regardless of outcome.
  if ! tags="$(curl -fsS --max-time 2 "${host}/api/tags" 2>/dev/null)"; then
    warn "Ollama not reachable at ${host} -- the UI runs, but chat needs a model. Start it and pull a model (e.g. 'ollama pull qwen3:8b'): ${DOC_LOCAL_CHAT}"
    return
  fi
  # A reachable server with no pulled model returns an empty "models" array.
  if printf '%s' "$tags" | grep -q '"name"'; then
    ok "Ollama reachable at ${host} (at least one model present)"
  else
    warn "Ollama reachable at ${host} but no model is pulled -- run 'ollama pull qwen3:8b'. See ${DOC_LOCAL_CHAT}"
  fi
}

run_dependency_checks() {
  step "Preflight: checking required tooling"
  check_uv
  check_node
  check_pnpm
  check_docker
  check_ollama
  if [ "$DEPS_OK" -ne 1 ]; then
    printf '\n'
    fail "One or more REQUIRED system dependencies are missing or too old (see [FAIL] lines above)."
    info "These are system-level tools this script will not auto-install. Install them, then re-run."
    info "Docs: ${DOC_TOOLCHAIN}  |  ${DOC_LOCAL_CHAT}  |  ${DOC_README}"
    exit 1
  fi
  ok "All required dependencies satisfied."
}

# --- Repo-local dependency install (idempotent; reuses make-target commands) -------------------
install_repo_deps() {
  step "Installing repo-local dependencies"
  info "Python deps: uv sync"
  uv sync
  ok "Python workspace synced (.venv)"
  info "JS deps: pnpm install"
  pnpm install
  ok "JS workspace installed (node_modules)"
}

# --- Database: bring up and wait for health (no migration step; backend self-migrates) ---------
DB_CONTAINER="personalai-db"
start_database() {
  step "Starting local Postgres + pgvector"
  info "docker compose up -d db"
  docker compose up -d db

  info "Waiting for Postgres to report healthy (compose pg_isready healthcheck) ..."
  local i status
  for i in $(seq 1 60); do
    # `docker inspect` exposes the compose healthcheck result. Tolerate transient errors.
    status="$(docker inspect -f '{{.State.Health.Status}}' "$DB_CONTAINER" 2>/dev/null || echo unknown)"
    case "$status" in
      healthy)
        ok "Postgres is healthy."
        return 0
        ;;
      unhealthy)
        fail "Postgres container reported 'unhealthy'. Inspect: docker logs ${DB_CONTAINER}"
        return 1
        ;;
    esac
    sleep 2
  done
  fail "Timed out waiting for Postgres to become healthy. Inspect: docker logs ${DB_CONTAINER}"
  return 1
}

# --- Run + monitor: plain-bash supervisor (zero new dependency) --------------------------------
# Backgrounded backend + UI jobs, each stream line-prefixed and colored. A single trap on
# EXIT/INT/TERM kills the whole process group so Ctrl-C cleanly stops everything. The DB container
# is intentionally left running (volume intact); we print how to stop it on exit.

# Prefix every line of stdin with a colored "[label]" tag.
prefix_stream() {
  local label="$1" color="$2"
  # `read -r` preserves backslashes; the trailing branch flushes a final line with no newline.
  while IFS= read -r line || [ -n "$line" ]; do
    printf '%s%s%s %s\n' "$color" "$label" "$RESET" "$line"
  done
}

shutdown() {
  # Idempotent: the EXIT trap may fire after an INT/TERM has already run this.
  trap - EXIT INT TERM
  printf '\n'
  info "Shutting down backend and UI ..."
  # Kill the whole process group (this script's children: backend, UI, their pipes).
  kill 0 2>/dev/null || true
  wait 2>/dev/null || true
  ok "Backend and UI stopped."
  info "The database container '${DB_CONTAINER}' is still running (data preserved)."
  info "Stop it with: ${BOLD}make db-down${RESET}"
}

run_stack() {
  step "Starting backend and UI"
  info "Backend -> http://127.0.0.1:8765   UI -> http://localhost:5173"
  info "Press Ctrl-C to stop everything (the DB container keeps running)."
  printf '\n'

  # One trap covers normal exit and signals; `kill 0` targets the whole process group.
  trap shutdown EXIT INT TERM

  # Backend: reuse the make-target command (uv run python -m personalai_backend). It auto-loads
  # .env and self-applies migrations on startup. 2>&1 merges stderr so logs interleave in order.
  ( uv run python -m personalai_backend 2>&1 | prefix_stream "[backend]" "$BLUE" ) &

  # UI: reuse the make-target command (pnpm --filter @personalai/ui dev -> Vite on :5173).
  ( pnpm --filter @personalai/ui dev 2>&1 | prefix_stream "[ui]" "$CYAN" ) &

  # Block until either child exits, then the EXIT trap tears the rest down. `wait -n` (bash >= 4.3)
  # returns as soon as any one job finishes; PID args are only honored on bash >= 5.1, so we pass
  # none and rely on "any job" semantics for portability across 4.3+.
  wait -n 2>/dev/null || true
}

# --- Argument parsing --------------------------------------------------------------------------
NO_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --no-run) NO_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *)
      fail "Unknown option: $1"
      printf '\n'
      usage
      exit 2
      ;;
  esac
  shift
done

# --- Main --------------------------------------------------------------------------------------
main() {
  # Run from the repo root regardless of where the script was invoked from.
  local script_dir repo_root
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  repo_root="$(cd "${script_dir}/.." && pwd)"
  cd "$repo_root"

  printf '%s\n' "${BOLD}PersonalAI bootstrap${RESET} -- semi-dev setup (db -> backend -> UI)"

  if [ ! -f .env ]; then
    warn ".env not found. The backend uses safe local-first defaults without it."
    info "To customize settings (model, ports, secrets), copy the template: cp .env.example .env"
    info "Never commit real secrets; .env.example documents every PERSONALAI_* setting."
  else
    ok ".env present (the backend auto-loads it; this script never reads its contents)."
  fi

  run_dependency_checks
  install_repo_deps
  start_database

  if [ "$NO_RUN" -eq 1 ]; then
    printf '\n'
    ok "Setup complete (--no-run). Dependencies installed and the database is up."
    info "Start the stack later with: ${BOLD}make dev${RESET}  (or run the backend and UI manually)."
    info "Stop the database with: ${BOLD}make db-down${RESET}"
    exit 0
  fi

  run_stack
}

main "$@"
