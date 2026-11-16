#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <sandbox-name>" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SANDBOX_NAME="$1"
SANDBOX_DIR="$DEMO_ROOT/sandboxes/$SANDBOX_NAME"

if [ -e "$SANDBOX_DIR" ]; then
  echo "Sandbox already exists: $SANDBOX_DIR" >&2
  exit 1
fi

mkdir -p "$SANDBOX_DIR/app" "$SANDBOX_DIR/runtime"
rsync -a \
  --exclude '.venv/' \
  --exclude 'data/runtime/' \
  --exclude 'data/generated/' \
  --exclude '__pycache__/' \
  "$DEMO_ROOT/app/" "$SANDBOX_DIR/app/"
rsync -a "$DEMO_ROOT/bin/" "$SANDBOX_DIR/bin/"
rsync -a "$DEMO_ROOT/datasets/" "$SANDBOX_DIR/datasets/"
cp "$DEMO_ROOT/AGENTS.md" "$SANDBOX_DIR/AGENTS.md"
cp "$DEMO_ROOT/README.md" "$SANDBOX_DIR/README.md"
cp "$DEMO_ROOT/.env.demo" "$SANDBOX_DIR/.env.demo"
chmod +x "$SANDBOX_DIR"/bin/*.sh

echo "$SANDBOX_DIR"
