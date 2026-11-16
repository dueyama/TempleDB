#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STARTER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$STARTER_ROOT/app"
VENV_PYTHON="$STARTER_ROOT/.venv/bin/python"
PYTHON_BIN="${PYTHON_BIN:-$VENV_PYTHON}"
RUNTIME_DIR="$STARTER_ROOT/runtime"
PRODUCT_DIR="$RUNTIME_DIR/product"
PRODUCT_DB="$PRODUCT_DIR/templedb.sqlite3"
PRODUCT_ENV="$PRODUCT_DIR/product.env"
TEMP_DB=""
TEMP_ENV=""

cleanup() {
  if [ -n "$TEMP_DB" ] && [ -e "$TEMP_DB" ]; then
    rm -f "$TEMP_DB" "${TEMP_DB}-journal" "${TEMP_DB}-shm" "${TEMP_DB}-wal"
  fi
  if [ -n "$TEMP_ENV" ] && [ -e "$TEMP_ENV" ]; then
    rm -f "$TEMP_ENV"
  fi
}

fail() {
  echo "$1" >&2
  exit 1
}

ensure_product_directory() {
  if [ -L "$RUNTIME_DIR" ]; then
    fail "Refusing product initialization because runtime/ is a symbolic link."
  fi
  mkdir -p "$RUNTIME_DIR"
  if [ -L "$PRODUCT_DIR" ]; then
    fail "Refusing product initialization because runtime/product/ is a symbolic link."
  fi
  if [ -e "$PRODUCT_DIR" ] && [ ! -d "$PRODUCT_DIR" ]; then
    fail "Product runtime path is not a directory: $PRODUCT_DIR"
  fi
  mkdir -p "$PRODUCT_DIR"
  chmod 700 "$PRODUCT_DIR"
}

ensure_product_environment() {
  if [ -L "$PRODUCT_ENV" ]; then
    fail "Refusing product initialization because product.env is a symbolic link."
  fi
  if [ -e "$PRODUCT_ENV" ]; then
    if [ ! -f "$PRODUCT_ENV" ]; then
      fail "Product environment path is not a regular file: $PRODUCT_ENV"
    fi
    chmod 600 "$PRODUCT_ENV"
    return
  fi

  local secret
  secret="$($PYTHON_BIN -c 'import secrets; print(secrets.token_urlsafe(48))')"
  umask 077
  TEMP_ENV="$(mktemp "$PRODUCT_DIR/.product.env.initializing.XXXXXX")"
  {
    echo "# Generated locally by bin/init_product_db.sh. Do not commit or share."
    echo "DJANGO_SECRET_KEY=$secret"
    echo "DJANGO_DEBUG=1"
    echo "DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost"
    echo "TEMPLEDB_RUNTIME_ROLE=staging"
    echo "TEMPLEDB_PRODUCT_HOST=127.0.0.1"
    echo "TEMPLEDB_PRODUCT_PORT=8010"
  } > "$TEMP_ENV"
  chmod 600 "$TEMP_ENV"
  if ! ln "$TEMP_ENV" "$PRODUCT_ENV" 2>/dev/null; then
    rm -f "$TEMP_ENV"
    TEMP_ENV=""
    fail "Product environment target appeared during initialization; refusing to overwrite it."
  fi
  rm -f "$TEMP_ENV"
  TEMP_ENV=""
  chmod 600 "$PRODUCT_ENV"
}

load_product_environment() {
  set -a
  # shellcheck disable=SC1090
  source "$PRODUCT_ENV"
  set +a
}

apply_sqlite_environment() {
  local database_path="$1"
  export TEMPLEDB_DEMO_MODE="0"
  export TEMPLEDB_DATABASE_ENGINE="sqlite"
  export TEMPLEDB_SQLITE_DB_PATH="$database_path"
  export DJANGO_DEBUG="${DJANGO_DEBUG:-1}"
  export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-127.0.0.1,localhost}"
  export DATABASE_HOST=""
  export DATABASE_NAME=""
  export DATABASE_USER=""
  export DATABASE_PASSWORD=""
  export DATABASE_PORT=""
  unset PYTEST_CURRENT_TEST
}

if [ ! -x "$PYTHON_BIN" ]; then
  fail "Python environment not found. Codex should run ./bin/setup.sh first."
fi
if [ ! -f "$APP_DIR/manage.py" ]; then
  fail "TempleDB application source was not found: $APP_DIR/manage.py"
fi

trap cleanup EXIT HUP INT TERM
ensure_product_directory

if [ -L "$PRODUCT_DB" ]; then
  fail "Refusing product initialization because the target database is a symbolic link."
fi
if [ -e "$PRODUCT_DB" ]; then
  fail "Product database already exists; no changes were made: $PRODUCT_DB"
fi

ensure_product_environment
load_product_environment
umask 077
TEMP_DB="$(mktemp "$PRODUCT_DIR/.templedb.sqlite3.initializing.XXXXXX")"
chmod 600 "$TEMP_DB"

apply_sqlite_environment "$TEMP_DB"
export DJANGO_SETTINGS_MODULE="config.settings_product_sqlite_initialization"

echo "Creating a new empty TempleDB product database in an isolated temporary file."
(
  cd "$APP_DIR"
  "$PYTHON_BIN" manage.py migrate --noinput
)

PRODUCT_VALIDATION_DB="$TEMP_DB" "$PYTHON_BIN" - <<'PY'
import os
import sqlite3
import sys
import uuid
from pathlib import Path

database_path = Path(os.environ["PRODUCT_VALIDATION_DB"])
required_business_tables = {
    "imports_household",
    "imports_person",
    "imports_deceasedprofile",
    "imports_serviceschedule",
}

with sqlite3.connect(database_path) as connection:
    quick_check = connection.execute("PRAGMA quick_check").fetchall()
    if quick_check != [("ok",)]:
        raise SystemExit(f"SQLite integrity check failed: {quick_check!r}")
    identity_rows = connection.execute(
        "SELECT installation_id, runtime_kind "
        "FROM core_databaseruntimeidentity WHERE singleton_key = 1"
    ).fetchall()
    if len(identity_rows) != 1:
        raise SystemExit("Product database identity is missing or ambiguous.")
    installation_id, runtime_kind = identity_rows[0]
    try:
        parsed_installation_id = uuid.UUID(str(installation_id))
    except (TypeError, ValueError) as exc:
        raise SystemExit("Product database installation ID is invalid.") from exc
    if parsed_installation_id.int == 0 or runtime_kind != "product":
        raise SystemExit(
            "Product database identity validation failed: "
            f"runtime_kind={runtime_kind!r}"
        )
    table_names = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    missing_tables = sorted(required_business_tables - table_names)
    if missing_tables:
        raise SystemExit(
            "Fresh product database is missing business tables: "
            + ", ".join(missing_tables)
        )
    empty_runtime_tables = sorted(
        table for table in table_names if table.startswith("imports_")
    )
    empty_runtime_tables.append("auth_user")
    counts = {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in empty_runtime_tables
    }
    nonempty = {table: count for table, count in counts.items() if count != 0}
    if nonempty:
        raise SystemExit(f"Fresh product database contains business rows: {nonempty!r}")

print("Product identity: product")
print(
    "Business rows: all imports_* tables=0, auth_user=0 "
    f"({len(empty_runtime_tables)} tables checked)"
)
PY

apply_sqlite_environment "$TEMP_DB"
export DJANGO_SETTINGS_MODULE="config.settings"
(
  cd "$APP_DIR"
  "$PYTHON_BIN" manage.py check --fail-level ERROR
)

if [ -e "$PRODUCT_DB" ]; then
  fail "Product database target appeared during initialization; refusing to overwrite it."
fi
PRODUCT_PUBLISH_SOURCE="$TEMP_DB" PRODUCT_PUBLISH_TARGET="$PRODUCT_DB" \
  "$PYTHON_BIN" - <<'PY'
import os
from pathlib import Path

source = Path(os.environ["PRODUCT_PUBLISH_SOURCE"])
target = Path(os.environ["PRODUCT_PUBLISH_TARGET"])

source_flags = os.O_RDONLY
if hasattr(os, "O_NOFOLLOW"):
    source_flags |= os.O_NOFOLLOW
source_fd = os.open(source, source_flags)
directory_fd = os.open(target.parent, os.O_RDONLY)
try:
    os.fsync(source_fd)
    try:
        os.link(source, target, follow_symlinks=False)
    except FileExistsError as exc:
        raise SystemExit(
            f"Product database target already exists; refusing to overwrite it: {target}"
        ) from exc
    os.fsync(directory_fd)
    os.unlink(source)
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
    os.close(source_fd)
PY
TEMP_DB=""
chmod 600 "$PRODUCT_DB"


echo
echo "Empty TempleDB product database is ready:"
echo "$PRODUCT_DB"
echo
echo "No demo rows or administrator password were copied into it."
echo "Next, Codex should run ./bin/create_product_admin.sh in an interactive terminal."
echo "After that, double-click TempleDB.command for normal use."
