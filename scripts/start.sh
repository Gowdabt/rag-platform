#!/usr/bin/env bash
# Start the local RAG platform: FastAPI (uvicorn) + Vite.
#
# Usage (from repo root or anywhere):
#   ./scripts/start.sh
#
# What it starts:
#   - API:  http://127.0.0.1:8000  (IPv4 loopback; avoids ::1 / localhost fetch issues)
#   - UI:   http://127.0.0.1:5173  (also http://localhost:5173)
#
# Does not start Electron. Ingestion jobs run in-process in the API
# (queue.provider=asyncio), so there is no separate worker.
#
# Env: sources repo-root .env if present, then forces RAG_CONFIG_DIR to
# configs/ and uses backend/.venv. PIDs and logs: .run/ (gitignored).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/_dev.sh
source "$SCRIPT_DIR/_dev.sh"

mkdir -p "$RUN_DIR"
load_env

if [[ ! -x "$UVICORN" ]]; then
  echo "Missing backend venv uvicorn. From the repo root:" >&2
  echo "  cd backend && python3.12 -m venv .venv && source .venv/bin/activate && pip install -e \".[dev]\"" >&2
  exit 1
fi

if [[ ! -x "$ROOT/frontend/node_modules/.bin/vite" ]]; then
  echo "Missing frontend deps. From the repo root:" >&2
  echo "  cd frontend && npm install" >&2
  exit 1
fi

already_api=0
already_fe=0

api_pid="$(read_pid_file "$API_PID_FILE")"
if [[ -n "$api_pid" ]] && is_our_api "$api_pid"; then
  already_api=1
elif [[ -n "$api_pid" ]]; then
  rm -f "$API_PID_FILE"
fi

fe_pid="$(read_pid_file "$FE_PID_FILE")"
if [[ -n "$fe_pid" ]] && is_our_frontend "$fe_pid"; then
  already_fe=1
elif [[ -n "$fe_pid" ]]; then
  rm -f "$FE_PID_FILE"
fi

# Occupied ports: refuse if a foreign process owns them; reuse if it is us.
for pid in $(listeners_on "$API_PORT"); do
  if is_our_api "$pid"; then
    already_api=1
    if [[ ! -f "$API_PID_FILE" ]]; then
      api_kill_root "$pid" > "$API_PID_FILE"
    fi
  else
    echo "Port ${API_PORT} is already in use by PID ${pid} (not this repo). Leave it alone and abort." >&2
    echo "  cwd=$(pid_cwd "$pid")" >&2
    echo "  cmd=$(pid_cmd "$pid")" >&2
    exit 1
  fi
done

for pid in $(listeners_on "$FE_PORT"); do
  if is_our_frontend "$pid"; then
    already_fe=1
    if [[ ! -f "$FE_PID_FILE" ]]; then
      frontend_kill_root "$pid" > "$FE_PID_FILE"
    fi
  else
    echo "Port ${FE_PORT} is already in use by PID ${pid} (not this repo). Leave it alone and abort." >&2
    echo "  cwd=$(pid_cwd "$pid")" >&2
    echo "  cmd=$(pid_cmd "$pid")" >&2
    exit 1
  fi
done

if (( already_api == 0 )); then
  : >"$API_LOG"
  spawn_daemon "$API_PID_FILE" "$API_LOG" "$ROOT/backend" \
    "$UVICORN" app.main:app --reload --host "$API_HOST" --port "$API_PORT"
  echo "Started API (pid $(cat "$API_PID_FILE")) → http://${API_HOST}:${API_PORT}"
else
  echo "API already running (pid $(cat "$API_PID_FILE")) → http://${API_HOST}:${API_PORT}"
fi

if (( already_fe == 0 )); then
  : >"$FE_LOG"
  spawn_daemon "$FE_PID_FILE" "$FE_LOG" "$ROOT/frontend" \
    "$(command -v npm)" run dev -- --port "$FE_PORT" --strictPort
  echo "Started Vite (pid $(cat "$FE_PID_FILE")) → http://${FE_HOST}:${FE_PORT}"
else
  echo "Vite already running (pid $(cat "$FE_PID_FILE")) → http://${FE_HOST}:${FE_PORT}"
fi

wait_http() {
  local url="$1"
  local i=0
  while (( i < 80 )); do
    if curl -sf -o /dev/null "$url"; then
      return 0
    fi
    sleep 0.25
    i=$((i + 1))
  done
  return 1
}

if ! wait_http "http://${API_HOST}:${API_PORT}/api/v1/health/live"; then
  echo "API did not become ready. See ${API_LOG}" >&2
  exit 1
fi

if ! wait_http "http://${FE_HOST}:${FE_PORT}/"; then
  echo "Vite did not become ready. See ${FE_LOG}" >&2
  exit 1
fi

echo "Logs: ${API_LOG}  ${FE_LOG}"
echo "Stop with: ./scripts/stop.sh"
