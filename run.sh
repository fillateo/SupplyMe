#!/usr/bin/env bash
#
# SupplyMe — local runner.
#
#   ./run.sh              set up if needed, then start the API and the console
#   ./run.sh mission      run one whole mission in the terminal, no servers
#   ./run.sh test         the test suite
#   ./run.sh mail         read the mailbox now instead of waiting for the poll
#   ./run.sh emulator     start the Firestore emulator and seed it from a backup
#
#   MOCK=true ./run.sh    replay a recorded mission instead of running one
#   ./run.sh stop         stop whatever this script started
#   ./run.sh status       what is running, and what it has spent
#   ./run.sh setup        install dependencies only
#   ./run.sh clean        remove build caches (never touches source or .env)
#
# No provider is ever simulated: real Gemini, the live web, Google Places, and a
# mailbox that actually sends. Credentials are not optional — a missing one
# stops the process and names itself, unless MOCK=true, which runs no mission at
# all and replays a recording of one. Set
# SUPPLYME_MAIL_REDIRECT_TO in backend/.env before running this against suppliers
# you have not agreed to contact.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
RUNDIR="$ROOT/.run"
VENV="$BACKEND/.venv"
PY="$VENV/bin/python"

API_PORT="${SUPPLYME_API_PORT:-8080}"
WEB_PORT="${SUPPLYME_WEB_PORT:-3000}"
# Not the emulator's own default of 8080: that is the API's port.
EMULATOR_PORT="${SUPPLYME_EMULATOR_PORT:-8085}"
EMULATOR_STARTED=0

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

find_gcloud() {
  # gcloud is frequently a shell alias rather than something on PATH — it is on
  # this machine — and a shell alias is invisible to any script or subprocess.
  # Look for the binary in the usual install locations instead of assuming.
  if command -v gcloud >/dev/null 2>&1; then command -v gcloud; return 0; fi
  local candidate
  for candidate in \
    "$HOME/google-cloud-sdk/bin/gcloud" \
    "/usr/lib/google-cloud-sdk/bin/gcloud" \
    "/usr/local/google-cloud-sdk/bin/gcloud" \
    "/opt/homebrew/share/google-cloud-sdk/bin/gcloud" \
    "/snap/bin/gcloud"
  do
    [ -x "$candidate" ] && { echo "$candidate"; return 0; }
  done
  return 1
}

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

port_busy() {
  ss -ltnH "sport = :$1" 2>/dev/null | grep -q .
}

free_port() {
  local port="$1" label="$2" pid
  pid="$(pid_on_port "$port" || true)"
  if [ -z "$pid" ]; then
    # Listening, but owned by a process this user cannot see. That is almost
    # always a published container port, since Docker forwards them as root,
    # and no amount of kill from here will move it.
    if port_busy "$port"; then
      warn "port $port is in use by a process this user cannot see ($label)"
      info "if that is the Docker stack, stop it with: docker compose down"
    fi
    return 0
  fi
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
  for name in api web emulator; do
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
  for port in "$API_PORT" "$WEB_PORT" "$EMULATOR_PORT"; do
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
    warn "wrote backend/.env from the example — fill in the credentials before starting"
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

cmd_mission() {
  check_prereqs; setup_backend
  say "running one complete mission in the terminal"
  info "real providers, real spend, and real email — check SUPPLYME_MAIL_REDIRECT_TO"
  echo
  (cd "$BACKEND" && "$PY" scripts/run_mission.py "$@")
}

cmd_mail() {
  check_prereqs
  say "reading the mailbox"
  curl -fsS -X POST "http://127.0.0.1:$API_PORT/webhooks/mail/poll" 2>/dev/null \
    || die "the API is not running on :$API_PORT"
  echo
}

start_services() {

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
    nohup "$VENV/bin/uvicorn" app.api.main:app \
      --host 127.0.0.1 --port "$API_PORT" > "$RUNDIR/api.log" 2>&1 &
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
  model="$("$PY" -c "
import json, sys
d = json.loads(sys.argv[1])
m = d.get('model') or {}
adapter = d.get('providers', {}).get('llm', '?')
tiers = ' / '.join(dict.fromkeys(x for x in (m.get('reasoning'), m.get('fast')) if x))
print(f\"{tiers} via {m.get('backend')}\" if tiers else adapter)
" "$health" 2>/dev/null || echo '?')"
  policy="$("$PY" -c "import json,sys;print(json.loads(sys.argv[1]).get('approval_policy','?'))" "$health" 2>/dev/null || echo '?')"

  echo
  printf '%s\n' "  ${BOLD}Console${OFF}   ${CYAN}http://localhost:$WEB_PORT${OFF}"
  printf '%s\n' "  ${BOLD}API docs${OFF}  ${CYAN}http://localhost:$API_PORT/docs${OFF}"
  echo
  printf '%s\n' "  model     $model"
  # The gate's own description has to follow the gate, or the line reassures you
  # about a review that is not going to happen.
  local approval_note
  case "$policy" in
    autonomous) approval_note="it sends without asking; only quotes and orders stop for a human" ;;
    strict)     approval_note="every outbound action is reviewed" ;;
    external)   approval_note="it will ask before the first email to each supplier" ;;
    *)          approval_note="" ;;
  esac
  printf '%s\n' "  approvals $policy${DIM}   ($approval_note)${OFF}"

  local mail_note
  mail_note="$("$PY" -c "
import json, sys
notes = json.loads(sys.argv[1]).get('notes', [])
print(next((n for n in notes if 'REDIRECT' in n or n.startswith('mail:')), ''))
" "$health" 2>/dev/null || echo "")"
  [ -n "$mail_note" ] && printf '%s\n' "  ${YELLOW}mail${OFF}      ${DIM}$mail_note${OFF}"

  local bound
  bound="$("$PY" -c "
import json, sys
p = json.loads(sys.argv[1]).get('providers', {})
print(', '.join(f'{k}={p[k]}' for k in ('search','maps','mail') if k in p))
" "$health" 2>/dev/null || echo "")"
  [ -n "$bound" ] && printf '%s\n' "  tools     $bound"
  printf '%s\n' "  spend     ${YELLOW}live${OFF} ${DIM}— ./run.sh status for this process${OFF}"
  echo
  printf '%s\n' "  ${DIM}Press ${OFF}Start sourcing${DIM}. What a run finds is up to the live web,${OFF}"
  printf '%s\n' "  ${DIM}so look for the shapes rather than for particular numbers:${OFF}"
  printf '%s\n' "  ${DIM}  · a red 'disagreement' badge — a supplier whose site and whose email${OFF}"
  printf '%s\n' "  ${DIM}    gave different answers, and the one follow-up that asks about it${OFF}"
  printf '%s\n' "  ${DIM}  · two suppliers claiming the same brand, judged differently${OFF}"
  printf '%s\n' "  ${DIM}  · click any number — it opens the source behind it${OFF}"
  echo
  printf '%s\n' "  ${DIM}logs: $RUNDIR/api.log, $RUNDIR/web.log     stop: ./run.sh stop${OFF}"
  echo
}

# --------------------------------------------------------------------------
# Firestore emulator
#
# The closest a laptop gets to the deployed data path: the same store adapter
# and the same client library, talking to a local process. Nothing reaches
# Google and nothing is billed, so a demo can be rehearsed as often as it needs
# to be.

# The emulator is a Java program. A system JRE is the normal answer; a JDK
# unpacked into ~/.local/jdk is the one that needs no root, and gcloud will not
# look there on its own.
find_java() {
  if command -v java >/dev/null 2>&1; then command -v java; return 0; fi
  local candidate
  for candidate in "$HOME/.local/jdk/bin/java" /usr/lib/jvm/*/bin/java; do
    [ -x "$candidate" ] && { printf '%s\n' "$candidate"; return 0; }
  done
  return 1
}

# MOCK=true ./run.sh — replays a recorded mission instead of running one, and
# therefore needs none of the credentials a real run cannot start without.
mock_on() {
  [ "${MOCK:-}" = "true" ] || [ "${SUPPLYME_MOCK:-}" = "true" ] \
    || grep -qE '^SUPPLYME_MOCK=true' "$BACKEND/.env" 2>/dev/null
}

emulator_configured() {
  grep -qE '^SUPPLYME_FIRESTORE_EMULATOR_HOST=.+' "$BACKEND/.env" 2>/dev/null
}

emulator_up() {
  curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:$EMULATOR_PORT/" 2>/dev/null
}

start_emulator() {
  if emulator_up; then
    info "the Firestore emulator is already up on :$EMULATOR_PORT"
    return 0
  fi

  local gcloud_bin
  gcloud_bin="$(find_gcloud || true)"
  [ -n "$gcloud_bin" ] || die "gcloud is not on PATH, and the emulator ships with it"
  local java_bin
  java_bin="$(find_java || true)"
  if [ -z "$java_bin" ]; then
    warn "the Firestore emulator needs Java, and none was found"
    info "either install one (sudo apt install default-jre), unpack a JRE into ~/.local/jdk,"
    info "or skip the host entirely and run: docker compose up --build"
    die "cannot start the emulator"
  fi
  JAVA_HOME="$(dirname "$(dirname "$java_bin")")"
  export JAVA_HOME
  export PATH="$JAVA_HOME/bin:$PATH"
  "$gcloud_bin" components list --format='value(id,state.name)' 2>/dev/null \
    | grep -q '^cloud-firestore-emulator.Installed$' \
    || die "run: gcloud components install cloud-firestore-emulator"

  free_port "$EMULATOR_PORT" "firestore emulator"
  mkdir -p "$RUNDIR"
  say "starting the Firestore emulator on :$EMULATOR_PORT"
  (
    nohup "$gcloud_bin" emulators firestore start \
      --host-port="127.0.0.1:$EMULATOR_PORT" > "$RUNDIR/emulator.log" 2>&1 &
    echo $! > "$RUNDIR/emulator.pid"
  )
  if ! wait_for_http "http://127.0.0.1:$EMULATOR_PORT/" emulator 60; then
    warn "the emulator did not come up. Last lines of $RUNDIR/emulator.log:"
    tail -15 "$RUNDIR/emulator.log" | sed 's/^/      /'
    die "startup failed"
  fi
  EMULATOR_STARTED=1
}

# The emulator holds everything in memory and starts empty every time, so this
# is part of starting it rather than a thing to remember. Writing the same
# document ids again is a no-op, so running it twice costs nothing.
seed_emulator() {
  (
    cd "$BACKEND"
    FIRESTORE_EMULATOR_HOST="127.0.0.1:$EMULATOR_PORT" \
      "$PY" scripts/seed_emulator.py "$@"
  )
}

cmd_emulator() {
  check_prereqs; setup_backend
  start_emulator
  say "seeding it from the newest snapshot"
  seed_emulator "$@"
  echo
  info "set this in backend/.env, then ./run.sh dev:"
  printf '%s\n' "      SUPPLYME_FIRESTORE_EMULATOR_HOST=127.0.0.1:$EMULATOR_PORT"
}

cmd_dev() {
  check_prereqs; setup_backend; setup_frontend

  # Started before the API, because the API builds its store at startup and a
  # Firestore client pointed at nothing is a slow, confusing failure.
  if emulator_configured; then
    EMULATOR_STARTED=0
    start_emulator
    # Only when this script started it. One that was already running has data
    # in it, possibly newer than any snapshot on disk.
    if [ "$EMULATOR_STARTED" = 1 ]; then
      say "seeding the emulator from the newest snapshot"
      seed_emulator
    fi
  fi

  if mock_on; then
    export MOCK=true
    warn "MOCK=true: missions are replayed from a recording, not run"
    info "no model, search, Places or mail provider is bound — see docs/LOCAL.md"
    start_services
    print_banner
    return 0
  fi

  # Every one of these is required to start. There is nothing to fall back to,
  # so failing here with the name of the missing variable beats failing four
  # minutes into a mission.
  local missing=""
  for key in SUPPLYME_PROJECT_ID SUPPLYME_MAPS_API_KEY SUPPLYME_SMTP_USER SUPPLYME_SMTP_PASSWORD; do
    grep -qE "^$key=.+" "$BACKEND/.env" 2>/dev/null || missing="$missing $key"
  done
  if [ -n "$missing" ]; then
    warn "backend/.env is missing:$missing"
    info "there is no offline mode — see backend/.env.example for what each one is"
    die "cannot start"
  fi
  if ! grep -qE '^SUPPLYME_MAIL_REDIRECT_TO=.+' "$BACKEND/.env" 2>/dev/null; then
    warn "SUPPLYME_MAIL_REDIRECT_TO is empty: outreach will go to real suppliers."
    info "set it to a mailbox you own unless that is what you meant."
  fi
  local gcloud_bin adc
  gcloud_bin="$(find_gcloud || true)"
  adc="${CLOUDSDK_CONFIG:-$HOME/.config/gcloud}/application_default_credentials.json"

  if [ -n "$gcloud_bin" ]; then
    if ! "$gcloud_bin" auth application-default print-access-token >/dev/null 2>&1; then
      warn "no application default credentials."
      info "run: gcloud auth application-default login"
      die "cannot start live"
    fi
  elif [ ! -f "$adc" ]; then
    warn "gcloud was not found and there are no application default credentials at:"
    info "$adc"
    info "install the Cloud SDK, then: gcloud auth application-default login"
    die "cannot start live"
  else
    info "gcloud not on PATH; using the credentials at $adc"
  fi

  local project vertex
  project="$(grep -E '^SUPPLYME_PROJECT_ID=' "$BACKEND/.env" | head -1 | cut -d= -f2 | tr -d '[:space:]')"
  # The Vertex endpoint, not SUPPLYME_LOCATION: reachability is a property of the
  # project and the endpoint together, and Gemini 3.x answers only from `global`.
  # Passing the region here reported every 3.x model as unreachable.
  vertex="$(grep -E '^SUPPLYME_VERTEX_LOCATION=' "$BACKEND/.env" | head -1 | cut -d= -f2 | tr -d '[:space:]')"
  say "checking which Gemini models $project can reach from ${vertex:-global}"
  (cd "$BACKEND" && "$PY" scripts/check_models.py --project "$project" \
      --location "${vertex:-global}" 2>/dev/null \
      | tail -5 | sed 's/^/    /') || warn "model check failed; starting anyway"

  start_services
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
  if emulator_configured || emulator_up; then
    emulator_up \
      && printf '%s\n' "  firestore${GREEN}up${OFF}   emulator     :$EMULATOR_PORT" \
      || printf '%s\n' "  firestore${DIM}down${OFF} ${DIM}emulator${OFF}"
  fi

  [ -n "$api_pid" ] || return 0
  echo
  curl -fsS "http://127.0.0.1:$API_PORT/api/health" 2>/dev/null | "$PY" -c '
import json, sys

d = json.load(sys.stdin)
spend = d.get("spend") or {}
total = spend.get("since_startup") or {}
caps = spend.get("caps_per_mission") or {}

m = d.get("model") or {}
tiers = " / ".join(dict.fromkeys(t for t in (m.get("reasoning"), m.get("fast")) if t))
# The adapter is called GeminiLLM whichever generation answered, so name the
# model. This is the line to read out loud when someone asks what it runs on.
# No single quotes below: this whole snippet lives inside a single-quoted
# shell string, and one apostrophe here silently truncates the program.
backend = m.get("backend") or "backend unknown"
print("  model    " + (tiers + "  (" + backend + ")" if tiers else d["providers"]["llm"]))
print("  policy   " + d["approval_policy"])

if total:
    # Dollars only. app/domain/quotes.py refuses to convert a currency without a
    # dated rate, and printing a rupiah figure here from a constant in a shell
    # script would be the same invention this system declines to make about a
    # supplier quote.
    print("  spent    {} model calls, ${:.4f} since startup".format(
        total.get("calls", 0), total.get("usd", 0.0)))
if caps:
    print("  caps     ${}/mission, {} model calls, {} emails".format(
        caps.get("usd"), caps.get("model_calls"), caps.get("outreach_emails")))
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
  mission)         shift || true; cmd_mission "$@" ;;
  mail)            shift || true; cmd_mail ;;
  emulator)        shift || true; cmd_emulator "$@" ;;
  test|tests)      shift || true; cmd_test "$@" ;;
  setup|install)   shift || true; cmd_setup ;;
  stop|down)       shift || true; stop_all ;;
  status|ps)       shift || true; cmd_status ;;
  clean)           shift || true; cmd_clean ;;
  -h|--help|help)  usage ;;
  *)               printf '%s\n\n' "${RED}unknown command:${OFF} $1"; usage; exit 2 ;;
esac
