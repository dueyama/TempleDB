#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STARTER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$STARTER_ROOT/app"
PYTHON_BIN="${PYTHON_BIN:-$STARTER_ROOT/.venv/bin/python}"
PRODUCT_DIR="$STARTER_ROOT/runtime/product"
PRODUCT_DB="$PRODUCT_DIR/templedb.sqlite3"
PRODUCT_ENV="$PRODUCT_DIR/product.env"

fail() {
  echo "$1" >&2
  exit 1
}

if [ ! -x "$PYTHON_BIN" ]; then
  fail "Python environment not found. Codex should run ./bin/setup.sh first."
fi
if [ -L "$PRODUCT_DB" ] || [ ! -f "$PRODUCT_DB" ]; then
  fail "Initialized product database not found. Codex should run ./bin/init_product_db.sh first."
fi
if [ -L "$PRODUCT_ENV" ] || [ ! -f "$PRODUCT_ENV" ]; then
  fail "Product environment not found. Codex should run ./bin/init_product_db.sh first."
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
export DATABASE_HOST=""
export DATABASE_NAME=""
export DATABASE_USER=""
export DATABASE_PASSWORD=""
export DATABASE_PORT=""
unset PYTEST_CURRENT_TEST

echo "Create the local TempleDB administrator named 'admin'."
echo "Enter the password directly in this terminal; it is not written to a settings file."
(
  cd "$APP_DIR"
  "$PYTHON_BIN" manage.py bootstrap_admin
)
