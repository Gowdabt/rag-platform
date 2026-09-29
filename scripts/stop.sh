#!/usr/bin/env bash
# Stop API (uvicorn :8000) and Vite (:5173) that belong to this repo.
#
# Usage:
#   ./scripts/stop.sh
#
# Stops processes recorded in .run/*.pid, then any leftover listeners on
# 8000/5173 whose cwd is this project's backend/ or frontend/. Does not
# kill unrelated apps on those ports.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/_dev.sh
source "$SCRIPT_DIR/_dev.sh"

stopped=0

stop_api_pid() {
  local pid="$1"
  [[ -n "$pid" ]] || return 0
  if is_our_api "$pid"; then
    local root
    root="$(api_kill_root "$pid")"
    echo "Stopping API pid ${root}"
    stop_pid "$root"
    stopped=1
  fi
}

stop_fe_pid() {
  local pid="$1"
  [[ -n "$pid" ]] || return 0
  if is_our_frontend "$pid"; then
    local root
    root="$(frontend_kill_root "$pid")"
    echo "Stopping Vite pid ${root}"
    stop_pid "$root"
    stopped=1
  fi
}

stop_api_pid "$(read_pid_file "$API_PID_FILE")"
stop_fe_pid "$(read_pid_file "$FE_PID_FILE")"

for pid in $(listeners_on "$API_PORT"); do
  stop_api_pid "$pid"
done

for pid in $(listeners_on "$FE_PORT"); do
  stop_fe_pid "$pid"
done

# npm run dev parent may not be the TCP listener; drop recorded frontend pid if still ours.
fe_pid="$(read_pid_file "$FE_PID_FILE")"
if [[ -n "$fe_pid" ]] && is_our_frontend "$fe_pid"; then
  stop_fe_pid "$fe_pid"
fi

rm -f "$API_PID_FILE" "$FE_PID_FILE"

leftover_api=0
leftover_fe=0
for pid in $(listeners_on "$API_PORT"); do
  if is_our_api "$pid"; then
    leftover_api=1
    echo "Warning: this project's API still listening on ${API_PORT} (pid ${pid})" >&2
  else
    echo "Left port ${API_PORT} PID ${pid} alone (not this repo)."
  fi
done
for pid in $(listeners_on "$FE_PORT"); do
  if is_our_frontend "$pid"; then
    leftover_fe=1
    echo "Warning: this project's Vite still listening on ${FE_PORT} (pid ${pid})" >&2
  else
    echo "Left port ${FE_PORT} PID ${pid} alone (not this repo)."
  fi
done

if (( leftover_api == 1 || leftover_fe == 1 )); then
  exit 1
fi

if (( stopped == 0 )); then
  echo "Nothing to stop (no rag-platform API/Vite processes)."
else
  echo "Stopped."
fi
