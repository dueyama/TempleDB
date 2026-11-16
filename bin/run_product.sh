#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STARTER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$STARTER_ROOT/app"
MANAGE_PY="$APP_DIR/manage.py"
PYTHON_BIN="${PYTHON_BIN:-$STARTER_ROOT/.venv/bin/python}"
PRODUCT_DIR="$STARTER_ROOT/runtime/product"
PRODUCT_DB="$PRODUCT_DIR/templedb.sqlite3"
PRODUCT_ENV="$PRODUCT_DIR/product.env"
PID_FILE="$PRODUCT_DIR/templedb-runserver.pid"
OPEN_BROWSER=0
SERVER_PID=""

usage() {
  cat <<'EOF'
Usage: ./bin/run_product.sh [--open-browser]

Starts the initialized local product SQLite database. It never creates or
migrates a missing database. If application updates require database
migrations, it stops and asks you to complete the backed-up upgrade with Codex.
EOF
}

fail() {
  echo "$1" >&2
  exit 1
}

is_positive_pid() {
  case "$1" in
    ""|*[!0-9]*) return 1 ;;
    *) [ "$1" -gt 0 ] ;;
  esac
}

cleanup_pid_file() {
  if [ -n "$SERVER_PID" ] && [ -f "$PID_FILE" ]; then
    local recorded_pid
    recorded_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ "$recorded_pid" = "$SERVER_PID" ]; then
      rm -f "$PID_FILE"
    fi
  fi
}

stop_child_on_signal() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --open-browser)
      OPEN_BROWSER=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ ! -x "$PYTHON_BIN" ]; then
  fail "Python environment not found. Open this folder in Codex and run ./bin/setup.sh."
fi
if [ -L "$PRODUCT_DB" ] || [ ! -f "$PRODUCT_DB" ]; then
  fail "Product database is not initialized. Open this folder in Codex and follow START_HERE.md."
fi
if [ -L "$PRODUCT_ENV" ] || [ ! -f "$PRODUCT_ENV" ]; then
  fail "Product environment is missing. Open this folder in Codex and follow START_HERE.md."
fi

set -a
# shellcheck disable=SC1090
source "$PRODUCT_ENV"
set +a

export DJANGO_SETTINGS_MODULE="config.settings"
export TEMPLEDB_DEMO_MODE="0"
export TEMPLEDB_DATABASE_ENGINE="sqlite"
export TEMPLEDB_SQLITE_DB_PATH="$PRODUCT_DB"
export DJANGO_DEBUG="${DJANGO_DEBUG:-1}"
export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-127.0.0.1,localhost}"
export TEMPLEDB_PRODUCT_HOST="${TEMPLEDB_PRODUCT_HOST:-127.0.0.1}"
export TEMPLEDB_PRODUCT_PORT="${TEMPLEDB_PRODUCT_PORT:-8010}"
export DATABASE_HOST=""
export DATABASE_NAME=""
export DATABASE_USER=""
export DATABASE_PASSWORD=""
export DATABASE_PORT=""
unset PYTEST_CURRENT_TEST

case "$TEMPLEDB_PRODUCT_HOST" in
  127.0.0.1|localhost) ;;
  *) fail "Starter product launcher only binds to 127.0.0.1 or localhost." ;;
esac
case "$TEMPLEDB_PRODUCT_PORT" in
  ""|*[!0-9]*) fail "TEMPLEDB_PRODUCT_PORT must be a number." ;;
esac
if [ "$TEMPLEDB_PRODUCT_PORT" -lt 1 ] || [ "$TEMPLEDB_PRODUCT_PORT" -gt 65535 ]; then
  fail "TEMPLEDB_PRODUCT_PORT must be between 1 and 65535."
fi

URL="http://$TEMPLEDB_PRODUCT_HOST:$TEMPLEDB_PRODUCT_PORT/"

if [ -f "$PID_FILE" ]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if is_positive_pid "$EXISTING_PID" && kill -0 "$EXISTING_PID" >/dev/null 2>&1; then
    EXISTING_COMMAND="$(/bin/ps -ww -p "$EXISTING_PID" -o command= 2>/dev/null || true)"
    if [[ "$EXISTING_COMMAND" == *"$PYTHON_BIN"*"$MANAGE_PY"*"runserver"*"$TEMPLEDB_PRODUCT_HOST:$TEMPLEDB_PRODUCT_PORT"* ]]; then
      echo "TempleDB product is already running at $URL"
      if [ "$OPEN_BROWSER" -eq 1 ] && command -v open >/dev/null 2>&1; then
        open "$URL" >/dev/null 2>&1 || true
      fi
      exit 0
    fi
    fail "Product PID file points to another live process; no signal was sent: $PID_FILE"
  fi
  rm -f "$PID_FILE"
fi

if ! (
  cd "$APP_DIR"
  "$PYTHON_BIN" manage.py migrate --check --skip-checks
); then
  fail "Product database schema needs an update. Open this folder in Codex and ask it to back up, test, and apply the pending migrations before starting TempleDB."
fi

(
  cd "$APP_DIR"
  "$PYTHON_BIN" manage.py check --fail-level ERROR
)

echo "Starting TempleDB product at $URL"
echo "To stop it, run ./bin/stop_product.sh or double-click TempleDB Stop.command."

"$PYTHON_BIN" "$MANAGE_PY" runserver --noreload --nothreading \
  "$TEMPLEDB_PRODUCT_HOST:$TEMPLEDB_PRODUCT_PORT" &
SERVER_PID="$!"
umask 077
echo "$SERVER_PID" > "$PID_FILE"
trap cleanup_pid_file EXIT
trap 'stop_child_on_signal' HUP INT TERM

if [ "$OPEN_BROWSER" -eq 1 ] && command -v open >/dev/null 2>&1; then
  (
    sleep 2
    open "$URL" >/dev/null 2>&1 || true
  ) &
fi

set +e
wait "$SERVER_PID"
STATUS="$?"
set -e
SERVER_PID="${SERVER_PID:-}"
exit "$STATUS"
