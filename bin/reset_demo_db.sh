#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -f "$DEMO_ROOT/.env.demo" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$DEMO_ROOT/.env.demo"
  set +a
fi

DB_PATH="$DEMO_ROOT/runtime/demo.sqlite3"
rm -f "$DB_PATH"
exec "$SCRIPT_DIR/init_demo_db.sh"
