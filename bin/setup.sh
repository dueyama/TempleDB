#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$DEMO_ROOT/app"
VENV_DIR="$DEMO_ROOT/.venv"
RUNTIME_DIR="$DEMO_ROOT/runtime"
ENV_CHANGE_LOG="$RUNTIME_DIR/environment_changes.md"
PIP_FREEZE_FILE="$RUNTIME_DIR/pip-freeze.txt"
VENV_ACTION="reused"

append_environment_log() {
  local scope="$1"
  local action="$2"
  local details="$3"
  local remove_command="$4"
  local timestamp
  local host_label
  local user_label

  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  host_label="$(hostname 2>/dev/null || echo unknown-host)"
  user_label="$(whoami 2>/dev/null || echo unknown-user)"
  mkdir -p "$RUNTIME_DIR"
  if [ ! -f "$ENV_CHANGE_LOG" ]; then
    cat > "$ENV_CHANGE_LOG" <<'EOF'
# TempleDB Demo Environment Changes

This file records environment changes made while preparing this disposable templedb-demo-workspace.
Local entries are safe to remove with `./bin/cleanup_demo_environment.sh --yes`.
Machine-level entries, such as Homebrew or apt packages, must be reviewed by Codex before removal.

EOF
  fi
  {
    echo "## $timestamp"
    echo "- scope: $scope"
    echo "- action: $action"
    echo "- details: $details"
    echo "- remove_command: \`$remove_command\`"
    echo "- user: $user_label"
    echo "- host: $host_label"
    echo
  } >> "$ENV_CHANGE_LOG"
}

python_is_demo_ready() {
  "$1" - <<'PY'
import sqlite3
import sys

raise SystemExit(0 if sys.version_info >= (3, 13) else 1)
PY
}

python_version_label() {
  "$1" - <<'PY'
import sys

print(".".join(str(part) for part in sys.version_info[:3]))
PY
}

select_python() {
  if [ -n "${PYTHON_BIN:-}" ]; then
    if try_python_candidate "$PYTHON_BIN"; then
      return
    fi
    echo "PYTHON_BIN did not meet demo requirements; checking other existing Python runtimes." >&2
  fi

  if try_python_candidate /opt/homebrew/bin/python3.13; then
    return
  fi
  if try_python_candidate /usr/local/bin/python3.13; then
    return
  fi
  try_python_candidate python3.13 && return

  if command -v pyenv >/dev/null 2>&1 && [ -f "$APP_DIR/.python-version" ]; then
    local pyenv_version
    local pyenv_prefix
    pyenv_version="$(cat "$APP_DIR/.python-version")"
    if pyenv_prefix="$(pyenv prefix "$pyenv_version" 2>/dev/null)"; then
      if try_python_candidate "$pyenv_prefix/bin/python"; then
        return
      fi
    fi
  fi

  try_python_candidate python3 && return
  try_python_candidate /usr/bin/python3 && return
  return 1
}

try_python_candidate() {
  local candidate="$1"
  local resolved=""

  if [ -z "$candidate" ]; then
    return 1
  fi

  if [ -x "$candidate" ]; then
    resolved="$candidate"
  elif command -v "$candidate" >/dev/null 2>&1; then
    resolved="$(command -v "$candidate")"
  else
    return 1
  fi

  if python_is_demo_ready "$resolved" >/dev/null 2>&1; then
    echo "$resolved"
    return 0
  fi
  return 1
}

if [ -d "$VENV_DIR" ]; then
  if [ -x "$VENV_DIR/bin/python" ]; then
    if python_is_demo_ready "$VENV_DIR/bin/python"; then
      echo "Reusing existing demo venv: $VENV_DIR"
    else
      echo "Existing demo venv is not compatible with TempleDB demo requirements."
      echo "Recreating only this local demo venv: $VENV_DIR"
      rm -rf "$VENV_DIR"
      VENV_ACTION="recreated-incompatible"
    fi
  else
    echo "Existing demo venv is incomplete or not portable."
    echo "Recreating only this local demo venv: $VENV_DIR"
    rm -rf "$VENV_DIR"
    VENV_ACTION="recreated-incomplete"
  fi
fi

if [ ! -d "$VENV_DIR" ]; then
  PYTHON_BIN="$(select_python)" || {
    echo "Python 3.13 or newer with sqlite3 support is required for TempleDB demo setup."
    echo "Codex should first look for an existing Python runtime."
    echo "If Homebrew is not installed and a new runtime is required, ask the user before installing Homebrew."
    echo "If Homebrew is available, install python@3.13 only after explaining that this changes the Mac environment."
    exit 1
  }

  if ! python_is_demo_ready "$PYTHON_BIN"; then
    echo "TempleDB demo requires Python 3.13 or newer with sqlite3 support."
    echo "Selected Python: $PYTHON_BIN ($(python_version_label "$PYTHON_BIN" 2>/dev/null || echo unknown))"
    echo "Codex should first look for another existing Python runtime."
    echo "If Homebrew is not installed and a new runtime is required, ask the user before installing Homebrew."
    echo "If Homebrew is available, install python@3.13 only after explaining that this changes the Mac environment."
    exit 1
  fi

  "$PYTHON_BIN" -m venv "$VENV_DIR"
  if [ "$VENV_ACTION" = "reused" ]; then
    VENV_ACTION="created"
  fi
fi

if ! "$VENV_DIR/bin/python" - <<'PY'
import sqlite3
import sys

raise SystemExit(0 if sys.version_info >= (3, 13) else 1)
PY
then
  echo "Python 3.13+ with sqlite3 support is missing in ${VENV_DIR}."
  echo "Remove ${VENV_DIR} and rerun setup after selecting a compatible Python runtime."
  exit 1
fi
"$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/config/dependencies/build.txt"
if [ "${TEMPLEDB_INSTALL_AI_TOOLS:-0}" = "1" ]; then
  "$VENV_DIR/bin/python" -m pip install --no-build-isolation -c "$APP_DIR/config/dependencies/runtime.txt" -c "$APP_DIR/config/dependencies/build.txt" -e "$APP_DIR[ai]"
  DEPENDENCY_SCOPE="pinned runtime plus optional AI/MCP dependencies (AI is outside the production baseline)"
else
  "$VENV_DIR/bin/python" -m pip install --no-build-isolation -c "$APP_DIR/config/dependencies/runtime.txt" -c "$APP_DIR/config/dependencies/build.txt" -e "$APP_DIR"
  DEPENDENCY_SCOPE="pinned editable app dependencies"
fi
"$VENV_DIR/bin/python" -m pip check
"$VENV_DIR/bin/python" "$APP_DIR/config/dependency_baseline.py" check --scope runtime
"$VENV_DIR/bin/python" "$APP_DIR/config/dependency_baseline.py" check --scope build
mkdir -p "$RUNTIME_DIR"
"$VENV_DIR/bin/python" -m pip freeze > "$PIP_FREEZE_FILE"
PYTHON_BIN="$VENV_DIR/bin/python" "$SCRIPT_DIR/ensure_demo_data.sh"
append_environment_log \
  "local-demo-workspace" \
  "setup.sh $VENV_ACTION" \
  "Prepared $VENV_DIR with $("$VENV_DIR/bin/python" --version 2>&1); installed $DEPENDENCY_SCOPE; verified demo SQLite database and export markers. Freeze: $PIP_FREEZE_FILE" \
  "./bin/cleanup_demo_environment.sh --yes"

echo "Demo dependencies are ready in $VENV_DIR"
echo "Environment changes recorded in $ENV_CHANGE_LOG"
