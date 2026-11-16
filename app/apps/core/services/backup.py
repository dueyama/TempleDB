from __future__ import annotations

import logging
import os as os
import subprocess as subprocess
import sys as sys
import time as time
from dataclasses import dataclass
from pathlib import Path

try:
    import psycopg as psycopg
except ModuleNotFoundError as exc:  # pragma: no cover - Windows native SQLite
    if exc.name != "psycopg":
        raise
    psycopg = None
from django.apps import apps as apps
from django.conf import settings as settings
from django.db import transaction as transaction
from django.db.models import Max as Max
from django.db.utils import OperationalError as OperationalError
from django.db.utils import ProgrammingError as ProgrammingError
from django.utils import timezone as timezone

from apps.core.models import (
    DatabaseBackupRun as DatabaseBackupRun,
)
from apps.core.models import (
    DatabaseBackupSetting as DatabaseBackupSetting,
)
from apps.core.models import (
    DatabaseBackupVerificationRun as DatabaseBackupVerificationRun,
)
from config.runtime_paths import BASE_DIR as BASE_DIR
from config.runtime_paths import runtime_root

from . import backup_bundle, backup_config, backup_execution, backup_schedule

logger = logging.getLogger(__name__)

VOLUMES_ROOT = Path("/Volumes")
BACKUP_LOCK_PATH = runtime_root() / "database_backup.lock"
SCHEDULE_LOCK_PATH = runtime_root() / "database_backup_schedule.lock"
SCHEDULE_CHECK_INTERVAL_SECONDS = 300.0
WEEKLY_VERIFICATION_INTERVAL_DAYS = 7
MAINTENANCE_RESERVATION_GRACE_SECONDS = 300.0
_last_schedule_check_monotonic = 0.0
_last_verification_schedule_check_monotonic = 0.0


class BackupServiceError(RuntimeError):
    pass


class BackupAlreadyRunningError(BackupServiceError):
    pass


@dataclass(frozen=True)
class PostgresConnectionConfig:
    database_name: str
    database_user: str
    database_password: str
    database_host: str
    database_port: str


@dataclass(frozen=True)
class PostgresAdminConfig:
    database_name: str
    database_user: str
    database_password: str
    database_host: str
    database_port: str


reset_schedule_check_cache = backup_schedule.reset_schedule_check_cache
is_postgresql_configured = backup_config.is_postgresql_configured
is_product_sqlite_configured = backup_config.is_product_sqlite_configured
current_database_engine = backup_config.current_database_engine
is_database_backup_supported = backup_config.is_database_backup_supported
backup_runs_for_current_engine = backup_config.backup_runs_for_current_engine
verification_runs_for_current_engine = backup_config.verification_runs_for_current_engine
get_or_create_backup_setting = backup_config.get_or_create_backup_setting
effective_backup_destination_path = backup_config.effective_backup_destination_path
backup_destination_path_source = backup_config.backup_destination_path_source
backup_destination_status_for_setting = backup_config.backup_destination_status_for_setting
list_available_volumes = backup_config.list_available_volumes
split_destination_path = backup_config.split_destination_path
backup_destination_status = backup_config.backup_destination_status
next_scheduled_run_label = backup_config.next_scheduled_run_label
next_scheduled_verification_label = backup_config.next_scheduled_verification_label
ensure_destination_directory = backup_config.ensure_destination_directory
resolve_destination_path = backup_config.resolve_destination_path
recent_backup_runs = backup_config.recent_backup_runs
recent_verification_runs = backup_config.recent_verification_runs
latest_successful_verification_run = backup_config.latest_successful_verification_run
latest_successful_scheduled_verification_run = (
    backup_config.latest_successful_scheduled_verification_run
)
latest_successful_backup_run = backup_config.latest_successful_backup_run
latest_failed_backup_run = backup_config.latest_failed_backup_run
latest_verification_for_backup_run = backup_config.latest_verification_for_backup_run
build_backup_migration_guide_context = backup_config.build_backup_migration_guide_context
build_backup_migration_bundle_filename = backup_bundle.build_backup_migration_bundle_filename
build_backup_migration_bundle_root_dir = backup_bundle.build_backup_migration_bundle_root_dir
build_backup_migration_bundle_entries = backup_bundle.build_backup_migration_bundle_entries
get_postgres_connection_config = backup_config.get_postgres_connection_config
get_postgres_admin_config = backup_config.get_postgres_admin_config
perform_database_backup = backup_execution.perform_database_backup
perform_backup_verification = backup_execution.perform_backup_verification
validate_backup_artifact = backup_execution.validate_backup_artifact
create_backup_migration_bundle = backup_bundle.create_backup_migration_bundle
build_pg_dump_command = backup_execution.build_pg_dump_command
build_createdb_command = backup_execution.build_createdb_command
build_pg_restore_command = backup_execution.build_pg_restore_command
build_dropdb_command = backup_execution.build_dropdb_command
inspect_restored_database = backup_execution.inspect_restored_database
build_postgres_env = backup_execution.build_postgres_env
calculate_sha256 = backup_execution.calculate_sha256
prune_old_backup_artifacts = backup_execution.prune_old_backup_artifacts
ensure_command_available = backup_execution.ensure_command_available
_run_command = backup_execution._run_command
_acquire_backup_lock = backup_execution._acquire_backup_lock
_acquire_verification_lock = backup_execution._acquire_verification_lock
_release_backup_lock = backup_execution._release_backup_lock
_read_lock_payload = backup_execution._read_lock_payload
_pid_is_alive = backup_execution._pid_is_alive
_lock_file_is_recent = backup_execution._lock_file_is_recent
_maintenance_lock_is_active = backup_execution._maintenance_lock_is_active
_update_setting_after_run = backup_execution._update_setting_after_run
maybe_dispatch_scheduled_backup = backup_schedule.maybe_dispatch_scheduled_backup
maybe_dispatch_scheduled_verification = backup_schedule.maybe_dispatch_scheduled_verification
_scheduled_verification_needed = backup_schedule._scheduled_verification_needed
spawn_scheduled_backup_process = backup_schedule.spawn_scheduled_backup_process
spawn_scheduled_verification_process = backup_schedule.spawn_scheduled_verification_process
_schedule_check_due = backup_schedule._schedule_check_due
_verification_schedule_check_due = backup_schedule._verification_schedule_check_due
_record_scheduled_spawn_failure = backup_schedule._record_scheduled_spawn_failure
_record_scheduled_verification_spawn_failure = (
    backup_schedule._record_scheduled_verification_spawn_failure
)
_acquire_schedule_lock = backup_schedule._acquire_schedule_lock
_release_schedule_lock = backup_schedule._release_schedule_lock
