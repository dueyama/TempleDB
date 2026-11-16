#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$DEMO_ROOT/runtime/environment_changes.md"
FREEZE_FILE="$DEMO_ROOT/runtime/pip-freeze.txt"

if [ -f "$LOG_FILE" ]; then
  sed -n '1,260p' "$LOG_FILE"
else
  echo "No environment change log found: $LOG_FILE"
fi

if [ -f "$FREEZE_FILE" ]; then
  echo
  echo "Python dependency freeze:"
  echo "$FREEZE_FILE"
fi
