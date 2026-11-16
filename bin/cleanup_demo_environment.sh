#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$DEMO_ROOT/runtime"
LOG_FILE="$RUNTIME_DIR/environment_changes.md"
DRY_RUN=1
MANAGED_SYSTEMD_UNITS=(
  "templedb-sqlite-demo.service"
  "templedb-postgresql-demo.service"
  "templedb-postgresql-demo-proxy.service"
)
SYSTEMD_UNIT_DIRS=(
  "/etc/systemd/system"
  "/etc/systemd/system/multi-user.target.wants"
  "/run/systemd/system"
  "/usr/local/lib/systemd/system"
  "/usr/lib/systemd/system"
  "/lib/systemd/system"
)

usage() {
  cat <<'EOF'
Usage:
  ./bin/cleanup_demo_environment.sh [--dry-run|--yes]

Removes generated local demo environment files only:
- .venv/
- runtime/demo.sqlite3
- runtime/templedb-demo-runserver.pid
- app/data/generated/
- Python cache directories inside app/

Machine-level changes such as Homebrew packages are not removed automatically.
Ask Codex to inspect runtime/environment_changes.md before removing them.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --yes)
      DRY_RUN=0
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

installed_unit_path() {
  local unit="$1"
  local unit_dir
  local candidate

  for unit_dir in "${SYSTEMD_UNIT_DIRS[@]}"; do
    candidate="$unit_dir/$unit"
    if [ -e "$candidate" ] || [ -L "$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

refuse_managed_systemd_cleanup() {
  local systemctl_bin=""
  local unit
  local unit_path
  local load_state
  local active_state
  local enabled_state
  local managed
  local -a findings=()

  systemctl_bin="$(command -v systemctl 2>/dev/null || true)"
  for unit in "${MANAGED_SYSTEMD_UNITS[@]}"; do
    unit_path=""
    load_state=""
    active_state=""
    enabled_state=""
    managed=0

    if unit_path="$(installed_unit_path "$unit")"; then
      managed=1
    fi

    if [ -n "$systemctl_bin" ]; then
      load_state="$(
        "$systemctl_bin" show --property=LoadState --value "$unit" 2>/dev/null ||
          true
      )"
      active_state="$("$systemctl_bin" is-active "$unit" 2>/dev/null || true)"
      enabled_state="$("$systemctl_bin" is-enabled "$unit" 2>/dev/null || true)"

      if [ -n "$load_state" ] && [ "$load_state" != "not-found" ]; then
        managed=1
      fi
      if "$systemctl_bin" is-active --quiet "$unit" >/dev/null 2>&1; then
        managed=1
      fi
      if "$systemctl_bin" is-enabled --quiet "$unit" >/dev/null 2>&1; then
        managed=1
      fi
    fi

    if [ "$managed" -eq 1 ]; then
      findings+=(
        "$unit (unit_file=${unit_path:-none}, load=${load_state:-unknown}, active=${active_state:-unknown}, enabled=${enabled_state:-unknown})"
      )
    fi
  done

  if [ "${#findings[@]}" -eq 0 ]; then
    return 0
  fi

  {
    echo "TempleDB demo systemd services are installed, active, or enabled."
    echo "Refusing to remove the local venv or demo SQLite database."
    echo "No local demo files were removed."
    echo
    echo "Detected managed services:"
    printf -- "- %s\n" "${findings[@]}"
    echo
    echo "Use the dedicated service removal procedure before local cleanup:"
    echo "1. Read docs/postgresql_demo_service.md and runtime/environment_changes.md."
    echo "2. Stop the proxy first, then disable and stop each detected Gunicorn service:"
    echo "   sudo systemctl disable --now templedb-postgresql-demo-proxy.service"
    echo "   sudo systemctl disable --now templedb-postgresql-demo.service"
    echo "   sudo systemctl disable --now templedb-sqlite-demo.service"
    echo "3. Remove only the installed TempleDB unit files, then run:"
    echo "   sudo systemctl daemon-reload"
    echo "   sudo systemctl reset-failed"
    echo "4. Review the recorded Caddy proxy root, Tailscale Serve route, and apt packages separately."
    echo "5. After all three units report not-found/inactive/disabled, rerun this cleanup command."
  } >&2
  return 1
}

if ! refuse_managed_systemd_cleanup; then
  exit 1
fi

remove_path() {
  local target="$1"
  if [ ! -e "$target" ]; then
    return
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "Would remove: $target"
  else
    rm -rf "$target"
    echo "Removed: $target"
  fi
}

remove_path "$DEMO_ROOT/.venv"
remove_path "$RUNTIME_DIR/demo.sqlite3"
remove_path "$RUNTIME_DIR/templedb-demo-runserver.pid"
remove_path "$DEMO_ROOT/app/data/generated"

if [ "$DRY_RUN" -eq 1 ]; then
  find "$DEMO_ROOT/app" -type d \( -name '__pycache__' -o -name '.pytest_cache' \) -print |
    sed 's/^/Would remove: /'
else
  find "$DEMO_ROOT/app" -type d \( -name '__pycache__' -o -name '.pytest_cache' \) -prune -exec rm -rf {} +
fi

if [ -f "$LOG_FILE" ]; then
  echo
  echo "Environment change log remains for Codex review:"
  echo "$LOG_FILE"
  echo "Machine-level remove_command entries are informational and require explicit review before use."
fi
