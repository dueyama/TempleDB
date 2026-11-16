#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$DEMO_ROOT/runtime"
LOG_FILE="$RUNTIME_DIR/environment_changes.md"

usage() {
  cat <<'EOF'
Usage:
  ./bin/record_machine_change.sh --action ACTION --details DETAILS --remove-command COMMAND

Example:
  ./bin/record_machine_change.sh \
    --action "homebrew install python@3.13" \
    --details "Installed Python 3.13 for TempleDB demo setup" \
    --remove-command "brew uninstall python@3.13"
EOF
}

ACTION=""
DETAILS=""
REMOVE_COMMAND=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --action)
      ACTION="${2:-}"
      shift 2
      ;;
    --details)
      DETAILS="${2:-}"
      shift 2
      ;;
    --remove-command)
      REMOVE_COMMAND="${2:-}"
      shift 2
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

if [ -z "$ACTION" ] || [ -z "$DETAILS" ] || [ -z "$REMOVE_COMMAND" ]; then
  usage >&2
  exit 2
fi

mkdir -p "$RUNTIME_DIR"
if [ ! -f "$LOG_FILE" ]; then
  cat > "$LOG_FILE" <<'EOF'
# TempleDB Demo Environment Changes

This file records environment changes made while preparing this disposable templedb-demo-workspace.
Local entries are safe to remove with `./bin/cleanup_demo_environment.sh --yes`.
Machine-level entries, such as Homebrew or apt packages, must be reviewed by Codex before removal.

EOF
fi

{
  echo "## $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "- scope: machine"
  echo "- action: $ACTION"
  echo "- details: $DETAILS"
  echo "- remove_command: \`$REMOVE_COMMAND\`"
  echo "- user: $(whoami 2>/dev/null || echo unknown-user)"
  echo "- host: $(hostname 2>/dev/null || echo unknown-host)"
  echo
} >> "$LOG_FILE"

echo "Recorded machine-level environment change in $LOG_FILE"
