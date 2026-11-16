from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import DatabaseBackupRun
from apps.core.services.database_transfer import (
    create_product_sqlite_clone_from_postgresql_backup,
)


class Command(BaseCommand):
    help = (
        "Create a fully verified product SQLite clone from a verified PostgreSQL backup "
        "without changing the live database configuration."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--backup-run-id", type=int, required=True)
        parser.add_argument("--output-path", type=Path, required=True)

    def handle(self, *args, **options) -> None:
        try:
            backup_run = DatabaseBackupRun.objects.get(pk=options["backup_run_id"])
        except DatabaseBackupRun.DoesNotExist as exc:
            raise CommandError("backup run was not found.") from exc

        try:
            result = create_product_sqlite_clone_from_postgresql_backup(
                backup_run=backup_run,
                output_path=options["output_path"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"SQLite clone created: {result.sqlite_path} "
                f"({result.transferred_object_count} objects, SHA256 {result.sqlite_sha256})"
            )
        )
        self.stdout.write(f"manifest: {result.manifest_path}")
        self.stdout.write(
            "The live database configuration was not changed. Activate this clone only "
            "after the source PostgreSQL runtime has been stopped."
        )
