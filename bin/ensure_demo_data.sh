#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$DEMO_ROOT/app"
VENV_PYTHON="$DEMO_ROOT/.venv/bin/python"
PYTHON_BIN="${PYTHON_BIN:-$VENV_PYTHON}"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Python environment not found. Run ./bin/setup.sh first." >&2
  exit 1
fi

if [ -f "$DEMO_ROOT/.env.demo" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$DEMO_ROOT/.env.demo"
  set +a
fi

export TEMPLEDB_DEMO_MODE="${TEMPLEDB_DEMO_MODE:-1}"
export TEMPLEDB_DATABASE_ENGINE="sqlite"
export DJANGO_SETTINGS_MODULE="config.settings"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-templedb-demo-unsafe-local-key}"
export DJANGO_DEBUG="${DJANGO_DEBUG:-1}"
export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-127.0.0.1,localhost}"
export TEMPLEDB_SQLITE_DB_PATH="$DEMO_ROOT/runtime/demo.sqlite3"
export TEMPLEDB_DEMO_DATASET_ID="synthetic_demo_v1"
export DEMO_ROOT
export DATABASE_HOST=""
export DATABASE_NAME=""
export DATABASE_USER=""
export DATABASE_PASSWORD=""
export DATABASE_PORT=""

check_demo_data() {
  "$PYTHON_BIN" - <<'PY'
import json
import os
import sqlite3
import sys
from pathlib import Path

demo_root = Path(os.environ["DEMO_ROOT"])
db_path = Path(os.environ["TEMPLEDB_SQLITE_DB_PATH"])
dataset_id = os.environ.get("TEMPLEDB_DEMO_DATASET_ID", "synthetic_demo_v1")
dataset_manifest_path = demo_root / "datasets" / dataset_id / "manifest.json"

missing = []
if not db_path.exists():
    missing.append(str(db_path))

try:
    dataset_manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    print(f"Demo dataset manifest is not readable: {dataset_manifest_path}: {exc}", file=sys.stderr)
    raise SystemExit(1)

source_id = dataset_manifest.get("source_id")
snapshot_id = dataset_manifest.get("prepared_snapshot_id")
if not source_id or not snapshot_id:
    print(f"Demo dataset manifest is missing source_id/prepared_snapshot_id: {dataset_manifest_path}", file=sys.stderr)
    raise SystemExit(1)

export_root = demo_root / "app" / "data" / "generated" / "legacy_exports" / source_id
latest_path = export_root / "latest.json"
snapshot_dir = export_root / snapshot_id
marker_files = [
    latest_path,
    snapshot_dir / "manifest.json",
    snapshot_dir / "export.log",
]
missing.extend(str(path) for path in marker_files if not path.exists())

if latest_path.exists():
    try:
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Demo export latest marker is invalid JSON: {latest_path}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    if latest.get("latest_snapshot_id") != snapshot_id:
        print(
            f"Demo export latest marker points to {latest.get('latest_snapshot_id')!r}, expected {snapshot_id!r}.",
            file=sys.stderr,
        )
        raise SystemExit(1)

if missing:
    print("Demo data is missing generated files:", file=sys.stderr)
    for path in missing:
        print(f"- {path}", file=sys.stderr)
    raise SystemExit(1)

try:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM imports_exportsnapshot snapshot
            JOIN imports_legacysource source ON snapshot.source_id = source.id
            WHERE source.source_id = ? AND snapshot.snapshot_id = ?
            """,
            (source_id, snapshot_id),
        ).fetchone()
        applied_migrations = {
            str(migration[0])
            for migration in connection.execute(
                """
                SELECT name
                FROM django_migrations
                WHERE app = ? AND name IN (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "imports",
                    "0052_rename_uid_database_columns",
                    "0054_rename_annual_fee_household_uid_column",
                    "0056_rename_hand_delivery_selected_household_uid_column",
                    "0057_promote_postal_review_selected_household_uid",
                    "0058_rename_postal_review_selected_household_uid_column",
                    "0059_promote_household_profile_mailing_person_uid",
                    "0060_rename_household_profile_mailing_person_uid_column",
                    "0061_promote_annual_fee_postal_scan_selected_household_uid",
                    "0062_rename_annual_fee_postal_scan_selected_household_uid_column",
                    "0063_promote_operational_household_uid",
                    "0064_rename_operational_household_uid_columns",
                    "0065_promote_operational_person_uid",
                    "0066_rename_operational_person_uid_columns",
                    "0067_remove_legacy_source_active_import_batch",
                ),
            )
        }
        uid_columns = {
            table_name: {
                str(column[1])
                for column in connection.execute(f"PRAGMA table_info({table_name})")
            }
            for table_name in (
                "imports_household",
                "imports_person",
                "imports_serviceschedule",
                "imports_visitnote",
                "imports_offeringpayment",
                "imports_annualmembershipfeepayment",
                "imports_handdeliveryreviewresolution",
                "imports_postalreviewresolution",
                "imports_householdprofile",
                "imports_annualmembershipfeepostalscan",
            )
        }
        legacy_source_columns = {
            str(column[1])
            for column in connection.execute(
                "PRAGMA table_info(imports_legacysource)"
            )
        }
except sqlite3.Error as exc:
    print(f"Demo SQLite database is not ready: {db_path}: {exc}", file=sys.stderr)
    raise SystemExit(1)

if not row or row[0] < 1:
    print(
        f"Demo SQLite database has no ExportSnapshot row for {source_id}/{snapshot_id}.",
        file=sys.stderr,
    )
    raise SystemExit(1)

main_uid_column_transitions = (
    ("imports_household", "legacy_household_id", "household_uid"),
    ("imports_person", "legacy_person_id", "person_uid"),
    ("imports_serviceschedule", "legacy_schedule_id", "schedule_uid"),
)
annual_fee_uid_column_transition = (
    "imports_annualmembershipfeepayment",
    "legacy_household_id",
    "household_uid",
)
hand_delivery_uid_column_transition = (
    "imports_handdeliveryreviewresolution",
    "legacy_household_id",
    "selected_household_uid",
)
postal_review_uid_column_transition = (
    "imports_postalreviewresolution",
    "legacy_household_id",
    "selected_household_uid",
)
household_profile_mailing_person_uid_column_transition = (
    "imports_householdprofile",
    "mailing_person_legacy_person_id",
    "mailing_person_uid",
)
annual_fee_postal_scan_selected_household_uid_column_transition = (
    "imports_annualmembershipfeepostalscan",
    "selected_legacy_household_id",
    "selected_household_uid",
)
operational_household_uid_column_transitions = (
    ("imports_serviceschedule", "legacy_household_id", "household_uid"),
    ("imports_visitnote", "legacy_household_id", "household_uid"),
    ("imports_offeringpayment", "legacy_household_id", "household_uid"),
)
operational_person_uid_column_transitions = (
    ("imports_serviceschedule", "legacy_person_id", "person_uid"),
    ("imports_visitnote", "legacy_person_id", "person_uid"),
    ("imports_offeringpayment", "legacy_person_id", "person_uid"),
)


def transition_layout(transitions):
    canonical = all(
        canonical_name in uid_columns[table_name]
        and legacy_name not in uid_columns[table_name]
        for table_name, legacy_name, canonical_name in transitions
    )
    legacy = all(
        legacy_name in uid_columns[table_name]
        and canonical_name not in uid_columns[table_name]
        for table_name, legacy_name, canonical_name in transitions
    )
    return canonical, legacy


main_canonical_layout, main_legacy_layout = transition_layout(
    main_uid_column_transitions
)
annual_fee_canonical_layout, annual_fee_legacy_layout = transition_layout(
    (annual_fee_uid_column_transition,)
)
hand_delivery_canonical_layout, hand_delivery_legacy_layout = transition_layout(
    (hand_delivery_uid_column_transition,)
)
postal_review_canonical_layout, postal_review_legacy_layout = transition_layout(
    (postal_review_uid_column_transition,)
)
(
    household_profile_mailing_person_canonical_layout,
    household_profile_mailing_person_legacy_layout,
) = transition_layout((household_profile_mailing_person_uid_column_transition,))
main_migration_applied = "0052_rename_uid_database_columns" in applied_migrations
annual_fee_migration_applied = (
    "0054_rename_annual_fee_household_uid_column" in applied_migrations
)
hand_delivery_migration_applied = (
    "0056_rename_hand_delivery_selected_household_uid_column" in applied_migrations
)
postal_review_alias_migration_applied = (
    "0057_promote_postal_review_selected_household_uid" in applied_migrations
)
postal_review_column_migration_applied = (
    "0058_rename_postal_review_selected_household_uid_column" in applied_migrations
)
mailing_person_alias_migration_applied = (
    "0059_promote_household_profile_mailing_person_uid" in applied_migrations
)
mailing_person_column_migration_applied = (
    "0060_rename_household_profile_mailing_person_uid_column"
    in applied_migrations
)
postal_scan_alias_migration_applied = (
    "0061_promote_annual_fee_postal_scan_selected_household_uid"
    in applied_migrations
)
postal_scan_column_migration_applied = (
    "0062_rename_annual_fee_postal_scan_selected_household_uid_column"
    in applied_migrations
)
operational_household_alias_migration_applied = (
    "0063_promote_operational_household_uid" in applied_migrations
)
operational_household_column_migration_applied = (
    "0064_rename_operational_household_uid_columns" in applied_migrations
)
operational_person_alias_migration_applied = (
    "0065_promote_operational_person_uid" in applied_migrations
)
operational_person_column_migration_applied = (
    "0066_rename_operational_person_uid_columns" in applied_migrations
)
active_import_batch_removal_migration_applied = (
    "0067_remove_legacy_source_active_import_batch" in applied_migrations
)
active_import_batch_column_present = (
    "active_import_batch_id" in legacy_source_columns
)
postal_scan_canonical_layout, postal_scan_legacy_layout = transition_layout(
    (annual_fee_postal_scan_selected_household_uid_column_transition,)
)
(
    operational_household_canonical_layout,
    operational_household_legacy_layout,
) = transition_layout(operational_household_uid_column_transitions)
(
    operational_person_canonical_layout,
    operational_person_legacy_layout,
) = transition_layout(operational_person_uid_column_transitions)
main_layout_aligned = (
    (main_migration_applied and main_canonical_layout)
    or (not main_migration_applied and main_legacy_layout)
)
annual_fee_layout_aligned = (
    (annual_fee_migration_applied and annual_fee_canonical_layout)
    or (not annual_fee_migration_applied and annual_fee_legacy_layout)
)
hand_delivery_layout_aligned = (
    (hand_delivery_migration_applied and hand_delivery_canonical_layout)
    or (not hand_delivery_migration_applied and hand_delivery_legacy_layout)
)
postal_review_layout_aligned = (
    (postal_review_column_migration_applied and postal_review_canonical_layout)
    or (not postal_review_column_migration_applied and postal_review_legacy_layout)
)
postal_review_migration_state_aligned = (
    not postal_review_column_migration_applied
    or postal_review_alias_migration_applied
)
mailing_person_layout_aligned = (
    (
        mailing_person_column_migration_applied
        and household_profile_mailing_person_canonical_layout
    )
    or (
        not mailing_person_column_migration_applied
        and household_profile_mailing_person_legacy_layout
    )
)
mailing_person_migration_state_aligned = (
    not mailing_person_alias_migration_applied
    or postal_review_column_migration_applied
) and (
    not mailing_person_column_migration_applied
    or mailing_person_alias_migration_applied
)
postal_scan_migration_state_aligned = (
    not postal_scan_alias_migration_applied
    or mailing_person_column_migration_applied
) and (
    not postal_scan_column_migration_applied
    or postal_scan_alias_migration_applied
)
postal_scan_layout_aligned = (
    postal_scan_column_migration_applied and postal_scan_canonical_layout
) or (
    not postal_scan_column_migration_applied and postal_scan_legacy_layout
)
operational_household_migration_state_aligned = (
    not operational_household_alias_migration_applied
    or postal_scan_column_migration_applied
) and (
    not operational_household_column_migration_applied
    or operational_household_alias_migration_applied
)
operational_household_layout_aligned = (
    operational_household_column_migration_applied
    and operational_household_canonical_layout
) or (
    not operational_household_column_migration_applied
    and operational_household_legacy_layout
)
operational_person_migration_state_aligned = (
    not operational_person_alias_migration_applied
    or operational_household_column_migration_applied
) and (
    not operational_person_column_migration_applied
    or operational_person_alias_migration_applied
)
operational_person_layout_aligned = (
    operational_person_column_migration_applied
    and operational_person_canonical_layout
) or (
    not operational_person_column_migration_applied
    and operational_person_legacy_layout
)
active_import_batch_migration_state_aligned = (
    not active_import_batch_removal_migration_applied
    or operational_person_column_migration_applied
)
active_import_batch_layout_aligned = (
    active_import_batch_removal_migration_applied
    and not active_import_batch_column_present
) or (
    not active_import_batch_removal_migration_applied
    and active_import_batch_column_present
)
canonical_layout = (
    main_canonical_layout
    and annual_fee_canonical_layout
    and hand_delivery_canonical_layout
    and postal_review_canonical_layout
    and household_profile_mailing_person_canonical_layout
    and postal_scan_canonical_layout
)
all_uid_migrations_applied = (
    main_migration_applied
    and annual_fee_migration_applied
    and hand_delivery_migration_applied
    and postal_review_alias_migration_applied
    and postal_review_column_migration_applied
    and mailing_person_alias_migration_applied
    and mailing_person_column_migration_applied
    and postal_scan_alias_migration_applied
    and postal_scan_column_migration_applied
    and operational_household_alias_migration_applied
    and operational_household_column_migration_applied
    and operational_person_alias_migration_applied
    and operational_person_column_migration_applied
    and active_import_batch_removal_migration_applied
)

if (
    all_uid_migrations_applied
    and canonical_layout
    and operational_household_canonical_layout
    and operational_person_canonical_layout
    and not active_import_batch_column_present
):
    raise SystemExit(0)
if (
    main_layout_aligned
    and annual_fee_layout_aligned
    and hand_delivery_layout_aligned
    and postal_review_layout_aligned
    and postal_review_migration_state_aligned
    and mailing_person_layout_aligned
    and mailing_person_migration_state_aligned
    and postal_scan_layout_aligned
    and postal_scan_migration_state_aligned
    and operational_household_layout_aligned
    and operational_household_migration_state_aligned
    and operational_person_layout_aligned
    and operational_person_migration_state_aligned
    and active_import_batch_layout_aligned
    and active_import_batch_migration_state_aligned
):
    print(
        "Demo SQLite database requires canonical UID column migrations.",
        file=sys.stderr,
    )
    raise SystemExit(2)

print(
    "Demo SQLite UID schema is inconsistent; refusing an automatic data reset. "
    "Run ./bin/reset_demo_db.sh explicitly if this disposable demo may be rebuilt.",
    file=sys.stderr,
)
raise SystemExit(3)
PY
}

migrations_are_current() {
  (
    cd "$APP_DIR"
    "$PYTHON_BIN" manage.py migrate --check --skip-checks
  )
}

upgrade_demo_schema() {
  echo "Upgrading the existing demo SQLite schema without resetting demo data."
  (
    cd "$APP_DIR"
    "$PYTHON_BIN" manage.py migrate --noinput --skip-checks
  )
  if ! check_demo_data; then
    echo "Demo SQLite schema upgrade did not reach a ready state." >&2
    exit 1
  fi
  if ! migrations_are_current; then
    echo "Demo SQLite schema upgrade left unapplied migrations." >&2
    exit 1
  fi
  echo "Demo SQLite schema upgrade completed."
}

if check_demo_data; then
  if migrations_are_current; then
    echo "Demo SQLite database and export markers are ready."
  else
    upgrade_demo_schema
  fi
else
  readiness_status=$?
  if [ "$readiness_status" -eq 2 ]; then
    upgrade_demo_schema
  elif [ "$readiness_status" -eq 1 ]; then
    echo "Regenerating demo SQLite database and export markers."
    "$SCRIPT_DIR/init_demo_db.sh"
  else
    exit "$readiness_status"
  fi
fi
