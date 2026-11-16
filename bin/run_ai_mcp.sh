#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$DEMO_ROOT/app"
VENV_PYTHON="$DEMO_ROOT/.venv/bin/python"
PYTHON_BIN="${PYTHON_BIN:-$VENV_PYTHON}"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Python environment not found. Run ./bin/setup.sh first." >&2
  exit 1
fi

if [ -f "$DEMO_ROOT/.env.demo" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$DEMO_ROOT/.env.demo"
  set +a
fi

export TEMPLEDB_DEMO_MODE="${TEMPLEDB_DEMO_MODE:-1}"
export TEMPLEDB_DATABASE_ENGINE="sqlite"
export TEMPLEDB_DEMO_DATASET_ID="synthetic_demo_v1"
export DJANGO_SETTINGS_MODULE="config.settings"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-templedb-demo-unsafe-local-key}"
export DJANGO_DEBUG="${DJANGO_DEBUG:-1}"
export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-127.0.0.1,localhost}"
export TEMPLEDB_SQLITE_DB_PATH="$DEMO_ROOT/runtime/demo.sqlite3"
export DATABASE_HOST=""
export DATABASE_NAME=""
export DATABASE_USER=""
export DATABASE_PASSWORD=""
export DATABASE_PORT=""

TRANSPORT="${TEMPLEDB_AI_MCP_TRANSPORT:-streamable-http}"
HOST="${TEMPLEDB_AI_MCP_HOST:-127.0.0.1}"
PORT="${TEMPLEDB_AI_MCP_PORT:-8765}"

cd "$APP_DIR"
if [ "$TRANSPORT" = "stdio" ]; then
  exec "$PYTHON_BIN" manage.py templedb_mcp_server --transport stdio "$@"
fi

echo "Starting TempleDB demo MCP at http://$HOST:$PORT/mcp" >&2
exec "$PYTHON_BIN" manage.py templedb_mcp_server \
  --transport "$TRANSPORT" \
  --host "$HOST" \
  --port "$PORT" \
  "$@"
