#!/usr/bin/env bash
#
# VendorDiscoveryShortcut — local runner.
#
#   ./run.sh              set up if needed, then start the API and the console
#   ./run.sh demo         run one whole mission in the terminal, no servers
#   ./run.sh test         the test suite
#   ./run.sh live         start against real Gemini instead of the scripted model
#   ./run.sh stop         stop whatever this script started
#   ./run.sh status       what is running, and what it has spent
#   ./run.sh setup        install dependencies only
#   ./run.sh clean        remove build caches (never touches source or .env)
#
# Defaults to the scripted model: no Google Cloud project, no API key, no
# network, no spend. `./run.sh live` is the opt-in.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
RUNDIR="$ROOT/.run"
VENV="$BACKEND/.venv"
PY="$VENV/bin/python"

API_PORT="${VDS_API_PORT:-8080}"
WEB_PORT="${VDS_WEB_PORT:-3000}"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
  YELLOW=$'\033[33m'; CYAN=$'\033[36m'; OFF=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; CYAN=""; OFF=""
fi

say()  { printf '%s\n' "${BOLD}==>${OFF} $*"; }
info() { printf '%s\n' "    ${DIM}$*${OFF}"; }
warn() { printf '%s\n' "    ${YELLOW}!${OFF} $*"; }
die()  { printf '%s\n' "${RED}✗${OFF} $*" >&2; exit 1; }

mkdir -p "$RUNDIR"

# --------------------------------------------------------------------------
# Prerequisites
# --------------------------------------------------------------------------

find_python() {
  # google-adk does not support 3.14 yet, so pick a version that works rather
  # than whatever `python3` happens to be.
  for candidate in python3.13 python3.12; do
    if command -v "$candidate" >/dev/null 2>&1; then echo "$candidate"; return; fi
  done
  if command -v python3 >/dev/null 2>&1; then
    local version
    version="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    case "$version" in
      3.12|3.13) echo python3; return ;;
    esac
  fi
  return 1
}

check_prereqs() {
  command -v node >/dev/null 2>&1 || die "node is not installed (need 20+)."
  local major
  major="$(node -v | sed 's/^v//' | cut -d. -f1)"
  [ "$major" -ge 20 ] || die "node $major is too old; need 20+."
}

# --------------------------------------------------------------------------
# Ports and processes
# --------------------------------------------------------------------------

pid_on_port() {
  # Deliberately not pgrep: matching a command-line pattern also matches this
  # script's own shell, which makes `kill` take the runner down with it.
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -lptnH "sport = :$port" 2>/dev/null | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2
  elif command -v lsof >/dev/null 2>&1; then
    lsof -ti ":$port" -sTCP:LISTEN 2>/dev/null | head -1
  fi
}

free_port() {
  local port="$1" label="$2" pid
  pid="$(pid_on_port "$port" || true)"
  [ -n "$pid" ] || return 0
  warn "port $port is in use by pid $pid; stopping it ($label)"
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    sleep 0.25
    [ -z "$(pid_on_port "$port" || true)" ] && return 0
  done
  kill -9 "$pid" 2>/dev/null || true
  sleep 0.5
}

wait_for_http() {
  local url="$1" label="$2" tries="${3:-60}"
  for _ in $(seq 1 "$tries"); do
    if curl -fsS -o /dev/null --max-time 2 "$url" 2>/dev/null; then return 0; fi
    sleep 1
  done
  return 1
}

stop_all() {
  local stopped=0
  for name in api web; do
    local file="$RUNDIR/$name.pid"
    [ -f "$file" ] || continue
    local pid; pid="$(cat "$file")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      stopped=1
    fi
    rm -f "$file"
  done
  # Anything still holding the ports, whether this script started it or not.
  for port in "$API_PORT" "$WEB_PORT"; do
    local pid; pid="$(pid_on_port "$port" || true)"
    if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || true; stopped=1; fi
  done
  [ "$stopped" = 1 ] && say "stopped" || info "nothing was running"
}

# --------------------------------------------------------------------------
# Setup
# --------------------------------------------------------------------------

setup_backend() {
  if [ ! -x "$PY" ]; then
    local python; python="$(find_python)" || die \
      "need Python 3.12 or 3.13 (google-adk does not support 3.14 yet). Install one and retry."
    say "creating the virtualenv with $python"
    if command -v uv >/dev/null 2>&1; then
      (cd "$BACKEND" && uv venv --python "$python" .venv >/dev/null)
    else
      "$python" -m venv "$VENV"
    fi
  fi

  # Cheap check that dependencies are present before reinstalling every run.
  if ! "$PY" -c 'import fastapi, google.adk, google.genai' >/dev/null 2>&1; then
    say "installing Python dependencies (a minute or two the first time)"
    if command -v uv >/dev/null 2>&1; then
      (cd "$BACKEND" && VIRTUAL_ENV="$VENV" uv pip install -e ".[dev]" >/dev/null)
    else
      "$VENV/bin/pip" install --quiet --upgrade pip
      (cd "$BACKEND" && "$VENV/bin/pip" install --quiet -e ".[dev]")
    fi
  fi

  if [ ! -f "$BACKEND/.env" ]; then
    cp "$BACKEND/.env.example" "$BACKEND/.env"
    info "wrote backend/.env (scripted model — no credentials, no spend)"
  fi
}

setup_frontend() {
  if [ ! -d "$FRONTEND/node_modules" ]; then
    say "installing Node dependencies"
    (cd "$FRONTEND" && npm install --silent)
  fi
}

# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

cmd_setup() {
  check_prereqs
  setup_backend
  setup_frontend
  say "ready"
  info "$($PY --version) · node $(node -v)"
}

cmd_test() {
  check_prereqs; setup_backend
  say "running the test suite"
  (cd "$BACKEND" && "$PY" -m pytest -q "$@")
}

cmd_demo() {
  check_prereqs; setup_backend
  say "running one complete mission in the terminal"
  info "scripted model — no credentials, no network, no spend"
  echo
  (cd "$BACKEND" && "$PY" scripts/run_demo.py "$@")
}

start_services() {
  local mode="$1"

  free_port "$API_PORT" "api"
  free_port "$WEB_PORT" "console"

  # `npm run build` and `next dev` share .next, and a production build run while
  # the dev server is up corrupts it into 500s. Start from a clean one.
  if [ -d "$FRONTEND/.next" ] && [ -f "$FRONTEND/.next/BUILD_ID" ]; then
    info "clearing a production build from .next so the dev server starts clean"
    mv "$FRONTEND/.next" "$RUNDIR/next-cache-$(date +%s)" 2>/dev/null || true
  fi

  say "starting the API on :$API_PORT"
  (
    cd "$BACKEND"
    if [ "$mode" = live ]; then
      VDS_USE_SCRIPTED_MODEL=false nohup "$VENV/bin/uvicorn" app.api.main:app \
        --host 127.0.0.1 --port "$API_PORT" > "$RUNDIR/api.log" 2>&1 &
    else
      VDS_USE_SCRIPTED_MODEL=true nohup "$VENV/bin/uvicorn" app.api.main:app \
        --host 127.0.0.1 --port "$API_PORT" > "$RUNDIR/api.log" 2>&1 &
    fi
    echo $! > "$RUNDIR/api.pid"
  )

  if ! wait_for_http "http://127.0.0.1:$API_PORT/healthz" api 40; then
    warn "the API did not come up. Last lines of $RUNDIR/api.log:"
    tail -15 "$RUNDIR/api.log" | sed 's/^/      /'
    die "startup failed"
  fi

  say "starting the console on :$WEB_PORT"
  (
    cd "$FRONTEND"
    API_BASE_URL="http://127.0.0.1:$API_PORT" nohup npm run dev \
      > "$RUNDIR/web.log" 2>&1 &
    echo $! > "$RUNDIR/web.pid"
  )

  if ! wait_for_http "http://127.0.0.1:$WEB_PORT/" console 90; then
    warn "the console did not come up. Last lines of $RUNDIR/web.log:"
    tail -15 "$RUNDIR/web.log" | sed 's/^/      /'
    die "startup failed"
  fi
}

print_banner() {
  local health model policy
  health="$(curl -fsS "http://127.0.0.1:$API_PORT/api/health" 2>/dev/null || echo '{}')"
  model="$("$PY" -c "import json,sys;print(json.loads(sys.argv[1]).get('providers',{}).get('llm','?'))" "$health" 2>/dev/null || echo '?')"
  policy="$("$PY" -c "import json,sys;print(json.loads(sys.argv[1]).get('approval_policy','?'))" "$health" 2>/dev/null || echo '?')"

  echo
  printf '%s\n' "  ${BOLD}Console${OFF}   ${CYAN}http://localhost:$WEB_PORT${OFF}"
  printf '%s\n' "  ${BOLD}API docs${OFF}  ${CYAN}http://localhost:$API_PORT/docs${OFF}"
  echo
  printf '%s\n' "  model     $model"
  printf '%s\n' "  approvals $policy${DIM}   (it will ask before the first email to each supplier)${OFF}"
  if [ "$model" = "ScriptedLLM" ]; then
    printf '%s\n' "  spend     ${GREEN}none${OFF} ${DIM}— deterministic model, no network${OFF}"
  else
    printf '%s\n' "  spend     ${YELLOW}live Gemini${OFF} ${DIM}— about \$0.05-0.08 per mission; ./run.sh status to check${OFF}"
  fi
  echo
  printf '%s\n' "  ${DIM}Press ${OFF}Start sourcing${DIM}, then look for:${OFF}"
  printf '%s\n' "  ${DIM}  · the supplier with the red 'disagreement' badge — website said MOQ 500,${OFF}"
  printf '%s\n' "  ${DIM}    their email said 1,000, so it called them${OFF}"
  printf '%s\n' "  ${DIM}  · two suppliers claiming the same brand, judged differently${OFF}"
  printf '%s\n' "  ${DIM}  · click any number — it opens the source behind it${OFF}"
  echo
  printf '%s\n' "  ${DIM}logs: $RUNDIR/api.log, $RUNDIR/web.log     stop: ./run.sh stop${OFF}"
  echo
}

cmd_dev() {
  check_prereqs; setup_backend; setup_frontend
  start_services demo
  print_banner
}

cmd_live() {
  check_prereqs; setup_backend; setup_frontend

  if ! grep -qE '^VDS_PROJECT_ID=.+' "$BACKEND/.env" 2>/dev/null; then
    warn "VDS_PROJECT_ID is not set in backend/.env — live mode needs a project."
    info "set it, then: gcloud auth application-default login"
    die "cannot start live"
  fi
  if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
    warn "no application default credentials."
    info "run: gcloud auth application-default login"
    die "cannot start live"
  fi

  say "checking which Gemini models this project can reach"
  (cd "$BACKEND" && "$PY" scripts/check_models.py \
      --project "$(grep -E '^VDS_PROJECT_ID=' "$BACKEND/.env" | cut -d= -f2)" 2>/dev/null \
      | tail -6 | sed 's/^/    /') || warn "model check failed; starting anyway"

  start_services live
  print_banner
}

cmd_status() {
  local api_pid web_pid
  api_pid="$(pid_on_port "$API_PORT" || true)"
  web_pid="$(pid_on_port "$WEB_PORT" || true)"

  [ -n "$api_pid" ] \
    && printf '%s\n' "  api      ${GREEN}up${OFF}   pid $api_pid   :$API_PORT" \
    || printf '%s\n' "  api      ${DIM}down${OFF}"
  [ -n "$web_pid" ] \
    && printf '%s\n' "  console  ${GREEN}up${OFF}   pid $web_pid   :$WEB_PORT" \
    || printf '%s\n' "  console  ${DIM}down${OFF}"

  [ -n "$api_pid" ] || return 0
  echo
  curl -fsS "http://127.0.0.1:$API_PORT/api/health" 2>/dev/null | "$PY" -c '
import json, sys

d = json.load(sys.stdin)
spend = d.get("spend") or {}
total = spend.get("since_startup") or {}
caps = spend.get("caps_per_mission") or {}

print("  model    " + d["providers"]["llm"])
print("  mode     " + d["mode"] + " / " + d["approval_policy"])

if total:
    usd = total.get("usd", 0.0)
    print("  spent    {} model calls, ${:.4f} (about Rp {:,.0f}) since startup".format(
        total.get("calls", 0), usd, usd * 16400))
if caps:
    print("  caps     ${}/mission, {} model calls, {} emails, {} phone calls".format(
        caps.get("usd"), caps.get("model_calls"),
        caps.get("outreach_emails"), caps.get("calls")))
for note in d.get("notes", []):
    print("  note     " + note)
' 2>/dev/null || warn "the API is up but did not answer /api/health"
}

cmd_clean() {
  say "removing build caches"
  local removed=0
  for path in "$FRONTEND/.next" "$FRONTEND/out" "$BACKEND/.pytest_cache" "$BACKEND/.ruff_cache"; do
    if [ -e "$path" ]; then rm -rf "$path"; info "removed ${path#$ROOT/}"; removed=1; fi
  done
  find "$BACKEND" -name '__pycache__' -type d -not -path '*/.venv/*' -prune -exec rm -rf {} + 2>/dev/null || true
  rm -rf "$RUNDIR"/next-cache-* 2>/dev/null || true
  [ "$removed" = 1 ] || info "nothing to remove"
  info "source, .env and the virtualenv are untouched"
}

usage() {
  # The header comment is the help text; print it until the first line that is
  # not a comment, so the two can never drift apart.
  awk 'NR<3 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"
}

case "${1:-dev}" in
  ""|dev|start|up) shift || true; cmd_dev ;;
  live)            shift || true; cmd_live ;;
  demo)            shift || true; cmd_demo "$@" ;;
  test|tests)      shift || true; cmd_test "$@" ;;
  setup|install)   shift || true; cmd_setup ;;
  stop|down)       shift || true; stop_all ;;
  status|ps)       shift || true; cmd_status ;;
  clean)           shift || true; cmd_clean ;;
  -h|--help|help)  usage ;;
  *)               printf '%s\n\n' "${RED}unknown command:${OFF} $1"; usage; exit 2 ;;
esac
