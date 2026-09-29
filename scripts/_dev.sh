# Shared helpers for scripts/start.sh, stop.sh, and restart.sh.
# Sourced only — not executed directly.

_DEV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$_DEV_DIR/.." && pwd)"
RUN_DIR="$ROOT/.run"

API_HOST="127.0.0.1"
API_PORT="8000"
FE_HOST="127.0.0.1"
FE_PORT="5173"

API_PID_FILE="$RUN_DIR/api.pid"
FE_PID_FILE="$RUN_DIR/frontend.pid"
API_LOG="$RUN_DIR/api.log"
FE_LOG="$RUN_DIR/frontend.log"

UVICORN="$ROOT/backend/.venv/bin/uvicorn"

pid_alive() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

pid_comm() {
  local raw
  raw="$(ps -o comm= -p "$1" 2>/dev/null || true)"
  raw="${raw##*/}"
  raw="${raw%% *}"
  printf '%s' "$raw"
}

_is_python() {
  case "$1" in
    Python|python|python3|python3.*|uvicorn) return 0 ;;
    *) return 1 ;;
  esac
}

_is_node() {
  case "$1" in
    node|node-*|vite|npm|npm-*) return 0 ;;
    *) return 1 ;;
  esac
}

pid_cwd() {
  lsof -a -p "$1" -d cwd -Fn 2>/dev/null | awk '/^n/ { print substr($0, 2); exit }'
}

pid_cmd() {
  ps -o command= -p "$1" 2>/dev/null || true
}

pid_ppid() {
  ps -o ppid= -p "$1" 2>/dev/null | tr -d ' '
}

# True if this PID is this repo's uvicorn (not an unrelated Python on :8000).
is_our_api() {
  local pid="${1:-}"
  pid_alive "$pid" || return 1
  local comm cwd cmd
  comm="$(pid_comm "$pid")"
  cwd="$(pid_cwd "$pid")"
  cmd="$(pid_cmd "$pid")"
  _is_python "$comm" || return 1
  [[ "$cwd" == "$ROOT/backend" || "$cwd" == "$ROOT/backend/"* ]] || return 1
  [[ "$cmd" == *"uvicorn"* && "$cmd" == *"app.main:app"* ]] && return 0
  # --reload child: multiprocessing spawn, still bound in this backend cwd
  [[ "$cmd" == *"multiprocessing"* || "$cmd" == *"spawn_main"* ]] && return 0
  return 1
}

# True if this PID is this repo's Vite (not some other app on :5173).
is_our_frontend() {
  local pid="${1:-}"
  pid_alive "$pid" || return 1
  local comm cwd cmd
  comm="$(pid_comm "$pid")"
  cwd="$(pid_cwd "$pid")"
  cmd="$(pid_cmd "$pid")"
  _is_node "$comm" || return 1
  [[ "$cwd" == "$ROOT/frontend" || "$cwd" == "$ROOT/frontend/"* ]] || return 1
  [[ "$cmd" == *"vite"* || "$cmd" == *"npm run dev"* ]] || return 1
  return 0
}

read_pid_file() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  tr -d ' \n' < "$file"
}

listeners_on() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | sort -u || true
}

# Walk up to the uvicorn reloader / npm parent, never into a shell.
api_kill_root() {
  local pid="$1" ppid
  while pid_alive "$pid"; do
    ppid="$(pid_ppid "$pid")"
    [[ -n "$ppid" && "$ppid" != "0" && "$ppid" != "1" ]] || break
    if is_our_api "$ppid"; then
      pid="$ppid"
      continue
    fi
    break
  done
  echo "$pid"
}

frontend_kill_root() {
  local pid="$1" ppid
  while pid_alive "$pid"; do
    ppid="$(pid_ppid "$pid")"
    [[ -n "$ppid" && "$ppid" != "0" && "$ppid" != "1" ]] || break
    if is_our_frontend "$ppid"; then
      pid="$ppid"
      continue
    fi
    break
  done
  echo "$pid"
}

kill_tree() {
  local pid="$1" child
  pid_alive "$pid" || return 0
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    kill_tree "$child"
  done
  kill -TERM "$pid" 2>/dev/null || true
}

wait_dead() {
  local pid="$1"
  local i=0
  while pid_alive "$pid" && (( i < 40 )); do
    sleep 0.15
    i=$((i + 1))
  done
  if pid_alive "$pid"; then
    for child in $(pgrep -P "$pid" 2>/dev/null || true); do
      kill -KILL "$child" 2>/dev/null || true
    done
    kill -KILL "$pid" 2>/dev/null || true
  fi
}

stop_pid() {
  local pid="$1"
  pid_alive "$pid" || return 0
  kill_tree "$pid"
  wait_dead "$pid"
}

load_env() {
  if [[ -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env"
    set +a
  fi
  # Always absolute so cwd changes (backend/) cannot pick the wrong YAML tree.
  export RAG_CONFIG_DIR="$ROOT/configs"
  export RAG_ENV="${RAG_ENV:-development}"
}

# Double-fork + setsid so API/Vite survive when this script's shell exits (SIGHUP).
spawn_daemon() {
  local pidfile="$1" logfile="$2" cwd="$3"
  shift 3
  "$ROOT/backend/.venv/bin/python" -c '
import os, sys
pidfile, logfile, cwd = sys.argv[1], sys.argv[2], sys.argv[3]
cmd = sys.argv[4:]
pid = os.fork()
if pid > 0:
    os.waitpid(pid, 0)
    raise SystemExit(0)
if os.fork() > 0:
    os._exit(0)
os.setsid()
os.chdir(cwd)
with open(pidfile, "w", encoding="utf-8") as fh:
    fh.write(str(os.getpid()) + "\n")
log = open(logfile, "ab", buffering=0)
devnull = os.open(os.devnull, os.O_RDONLY)
os.dup2(devnull, 0)
os.dup2(log.fileno(), 1)
os.dup2(log.fileno(), 2)
os.close(devnull)
os.execvpe(cmd[0], cmd, os.environ)
' "$pidfile" "$logfile" "$cwd" "$@"
  local i=0
  while [[ ! -s "$pidfile" ]] && (( i < 50 )); do
    sleep 0.05
    i=$((i + 1))
  done
  local spawned
  spawned="$(read_pid_file "$pidfile")"
  if ! pid_alive "$spawned"; then
    echo "Failed to spawn: $*" >&2
    return 1
  fi
}
