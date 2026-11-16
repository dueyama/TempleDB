#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STARTER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$STARTER_ROOT/.venv/bin/python}"
MANAGE_PY="$STARTER_ROOT/app/manage.py"
PID_FILE="$STARTER_ROOT/runtime/product/templedb-runserver.pid"

is_positive_pid() {
  case "$1" in
    ""|*[!0-9]*) return 1 ;;
    *) [ "$1" -gt 0 ] ;;
  esac
}

if [ ! -f "$PID_FILE" ]; then
  echo "TempleDB product PID file was not found."
  exit 0
fi

SERVER_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
if ! is_positive_pid "$SERVER_PID"; then
  echo "Removing invalid TempleDB product PID file."
  rm -f "$PID_FILE"
  exit 0
fi
if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
  echo "Removing stale TempleDB product PID file."
  rm -f "$PID_FILE"
  exit 0
fi

SERVER_COMMAND="$(/bin/ps -ww -p "$SERVER_PID" -o command= 2>/dev/null || true)"
if [[ "$SERVER_COMMAND" != *"$PYTHON_BIN"*"$MANAGE_PY"*"runserver"* ]]; then
  echo "PID file does not identify this TempleDB product; no signal was sent." >&2
  exit 1
fi

echo "Stopping TempleDB product ($SERVER_PID)..."
kill "$SERVER_PID"

for _ in {1..30}; do
  if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    rm -f "$PID_FILE"
    echo "TempleDB product stopped."
    exit 0
  fi
  sleep 0.1
done

echo "TempleDB product is still stopping; no force-kill was sent." >&2
echo "Run this stop command again after a moment." >&2
exit 1
