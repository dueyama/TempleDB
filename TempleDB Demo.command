#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:${PATH}"

APP_DIR="app"
RUNTIME_DIR="runtime"
PID_FILE="${RUNTIME_DIR}/templedb-demo-runserver.pid"
VENV_DIR=".venv"
VENV_PYTHON="${VENV_DIR}/bin/python"
DEMO_ROOT="${PWD}"
PYTHON_EXEC="${DEMO_ROOT}/${VENV_PYTHON}"
MANAGE_PY="${DEMO_ROOT}/${APP_DIR}/manage.py"

load_demo_env() {
  if [ -f ".env.demo" ]; then
    set -a
    source ".env.demo"
    set +a
  fi
}

apply_defaults() {
  export DJANGO_SETTINGS_MODULE="config.settings"
  export DJANGO_DEBUG="${DJANGO_DEBUG:-1}"
  export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-127.0.0.1,localhost}"
  export TEMPLEDB_DEMO_MODE="${TEMPLEDB_DEMO_MODE:-1}"
  export TEMPLEDB_DATABASE_ENGINE="sqlite"
  export TEMPLEDB_DEMO_HOST="${TEMPLEDB_DEMO_HOST:-127.0.0.1}"
  export TEMPLEDB_DEMO_PORT="${TEMPLEDB_DEMO_PORT:-8011}"
  export TEMPLEDB_DEMO_DATASET_ID="synthetic_demo_v1"
  export TEMPLEDB_DEMO_USERNAME="${TEMPLEDB_DEMO_USERNAME:-demo}"
  export TEMPLEDB_DEMO_PASSWORD="${TEMPLEDB_DEMO_PASSWORD:-demo}"
  export TEMPLEDB_SQLITE_DB_PATH="${PWD}/${RUNTIME_DIR}/demo.sqlite3"
  export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-templedb-demo-unsafe-local-key}"
  export DATABASE_HOST=""
  export DATABASE_NAME=""
  export DATABASE_USER=""
  export DATABASE_PASSWORD=""
  export DATABASE_PORT=""
}

ensure_runtime_dir() {
  mkdir -p "${RUNTIME_DIR}"
}

ensure_venv_ready() {
  if [ -x "${VENV_PYTHON}" ]; then
    return
  fi
  echo "Demo Python environment is not ready."
  echo "Open this folder in Codex and ask it to set up the templedb-demo-workspace environment using AGENTS.md."
  echo "Expected Python: ${VENV_PYTHON}"
  exit 1
}

ensure_demo_database_ready() {
  ./bin/ensure_demo_data.sh
}

is_positive_pid() {
  case "$1" in
    ""|*[!0-9]*) return 1 ;;
    *) [ "$1" -gt 0 ] ;;
  esac
}

ensure_not_already_running() {
  if [ ! -f "${PID_FILE}" ]; then
    return
  fi
  local existing_pid
  local existing_command
  existing_pid="$(cat "${PID_FILE}")"
  if is_positive_pid "${existing_pid}" \
    && kill -0 "${existing_pid}" >/dev/null 2>&1; then
    existing_command="$(/bin/ps -ww -p "${existing_pid}" -o command= 2>/dev/null || true)"
    if [[ "${existing_command}" == *"${PYTHON_EXEC}"*"${MANAGE_PY}"*"runserver"* ]]; then
      local url="http://${TEMPLEDB_DEMO_HOST}:${TEMPLEDB_DEMO_PORT}/"
      echo "TempleDB demo is already running at ${url}"
      open "${url}" >/dev/null 2>&1 || true
      exit 0
    fi
  fi
  rm -f "${PID_FILE}"
}

load_demo_env
apply_defaults
ensure_runtime_dir
ensure_venv_ready
ensure_demo_database_ready
ensure_not_already_running

URL="http://${TEMPLEDB_DEMO_HOST}:${TEMPLEDB_DEMO_PORT}/"

echo "Starting TempleDB demo at ${URL}"
echo "To stop: press Ctrl-C in this window or run 'TempleDB Demo Stop.command'."

( sleep 2 && open "${URL}" ) >/dev/null 2>&1 &
echo "$$" > "${PID_FILE}"
cd "${APP_DIR}"
exec "${PYTHON_EXEC}" "${MANAGE_PY}" runserver "${TEMPLEDB_DEMO_HOST}:${TEMPLEDB_DEMO_PORT}"
