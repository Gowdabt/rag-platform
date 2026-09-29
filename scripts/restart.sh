#!/usr/bin/env bash
# Stop then start the local RAG platform (API + Vite). See start.sh / stop.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/stop.sh"
"$SCRIPT_DIR/start.sh"
