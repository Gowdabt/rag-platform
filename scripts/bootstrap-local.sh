#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PG_BIN="/opt/homebrew/opt/postgresql@17/bin"
PGDATA="/opt/homebrew/var/postgresql@17"
LOG="/opt/homebrew/var/log/postgresql@17.log"

if [[ ! -x "$PG_BIN/pg_ctl" ]]; then
  echo "Install Postgres 17 + pgvector: brew install postgresql@17 pgvector" >&2
  exit 1
fi

mkdir -p "$(dirname "$LOG")"
if ! "$PG_BIN/pg_isready" -q; then
  "$PG_BIN/pg_ctl" -D "$PGDATA" -l "$LOG" start
fi

"$PG_BIN/psql" postgres -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag') THEN
    CREATE ROLE rag LOGIN PASSWORD 'rag' SUPERUSER;
  END IF;
END
$$;
SQL

if ! "$PG_BIN/psql" -lqt | cut -d \| -f 1 | grep -qw rag; then
  "$PG_BIN/createdb" -O rag rag
fi

"$PG_BIN/psql" rag -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;"
"$PG_BIN/psql" rag -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS citext;"

if [[ ! -f "$ROOT/.env" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
fi

cd "$ROOT/backend"
export RAG_CONFIG_DIR="$ROOT/configs"
export RAG_ENV=development
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a
"$ROOT/backend/.venv/bin/alembic" upgrade head
echo "Postgres is ready and migrations are applied."
