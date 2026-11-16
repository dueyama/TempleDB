from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import DatabaseBackupRun
from apps.core.services.database_transfer_postgresql import (
    create_product_postgresql_clone_from_sqlite_backup,
)


class Command(BaseCommand):
    help = (
        "Create a fully verified, frozen PostgreSQL clone from a verified product "
        "SQLite backup without changing the live database configuration."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--backup-run-id", type=int, required=True)
        parser.add_argument("--target-database-name", required=True)
        parser.add_argument("--manifest-path", type=Path, required=True)
        parser.add_argument("--confirm-target-database-name", required=True)

    def handle(self, *args, **options) -> None:
        target_database_name = options["target_database_name"].strip()
        confirmed_database_name = options["confirm_target_database_name"].strip()
        if target_database_name != confirmed_database_name:
            raise CommandError(
                "--confirm-target-database-name must exactly match "
                "--target-database-name."
            )

        try:
            backup_run = DatabaseBackupRun.objects.get(pk=options["backup_run_id"])
        except DatabaseBackupRun.DoesNotExist as exc:
            raise CommandError("backup run was not found.") from exc

        try:
            result = create_product_postgresql_clone_from_sqlite_backup(
                backup_run=backup_run,
                target_database_name=target_database_name,
                manifest_path=options["manifest_path"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"PostgreSQL clone created and frozen: {result.database_name} "
                f"({result.transferred_object_count} objects, OID {result.database_oid})"
            )
        )
        self.stdout.write(f"source backup run: {result.source_backup_run_id}")
        self.stdout.write(f"source verification run: {result.source_verification_run_id}")
        self.stdout.write(f"manifest: {result.manifest_path}")
        self.stdout.write(f"completion marker: {result.completion_marker_path}")
        self.stdout.write("connections allowed: no")
        self.stdout.write(
            "The live SQLite configuration was not changed. Activation is a separate operation."
        )
