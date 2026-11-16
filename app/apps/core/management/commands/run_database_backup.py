from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.core.services import backup


class Command(BaseCommand):
    help = "Create a backup for the current TempleDB database engine."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--trigger",
            choices=["manual", "scheduled"],
            default="manual",
        )
        parser.add_argument(
            "--requested-by",
            default="",
        )

    def handle(self, *args, **options) -> None:
        try:
            run = backup.perform_database_backup(
                trigger_kind=options["trigger"],
                requested_by_label=options["requested_by"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"backup run {run.id} finished: {run.backup_file_name or run.status}"
            )
        )
