#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

RUNTIME_DIR="runtime"
PID_FILE="${RUNTIME_DIR}/templedb-demo-runserver.pid"
PYTHON_EXEC="${PWD}/.venv/bin/python"
MANAGE_PY="${PWD}/app/manage.py"

is_positive_pid() {
  case "$1" in
    ""|*[!0-9]*) return 1 ;;
    *) [ "$1" -gt 0 ] ;;
  esac
}

if [ -f "${PID_FILE}" ]; then
  SERVER_PID="$(cat "${PID_FILE}")"
  if is_positive_pid "${SERVER_PID}" \
    && kill -0 "${SERVER_PID}" >/dev/null 2>&1; then
    SERVER_COMMAND="$(/bin/ps -ww -p "${SERVER_PID}" -o command= 2>/dev/null || true)"
    if [[ "${SERVER_COMMAND}" == *"${PYTHON_EXEC}"*"${MANAGE_PY}"*"runserver"* ]]; then
      echo "Stopping TempleDB demo (${SERVER_PID})..."
      kill "${SERVER_PID}" >/dev/null 2>&1 || true
      sleep 1
    else
      echo "PID file does not identify this TempleDB demo; no signal was sent."
    fi
  fi
  rm -f "${PID_FILE}"
else
  echo "TempleDB demo PID file was not found."
fi

echo "TempleDB demo stop request completed."
