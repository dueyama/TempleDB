from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import DatabaseBackupVerificationRun
from apps.core.services import backup


class Command(BaseCommand):
    help = "Restore a backup into a temporary database and verify basic table access."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--run-id", type=int, required=True)
        parser.add_argument("--verification-id", type=int)
        parser.add_argument(
            "--trigger",
            choices=["manual", "scheduled"],
            default="manual",
        )
        parser.add_argument("--requested-by", default="")

    def handle(self, *args, **options) -> None:
        try:
            backup_run = backup.backup_runs_for_current_engine().get(pk=options["run_id"])
        except backup.DatabaseBackupRun.DoesNotExist as exc:
            raise CommandError("backup run was not found.") from exc

        verification_run = None
        if options["verification_id"] is not None:
            try:
                verification_run = DatabaseBackupVerificationRun.objects.get(
                    pk=options["verification_id"],
                    backup_run=backup_run,
                )
            except DatabaseBackupVerificationRun.DoesNotExist as exc:
                raise CommandError("verification run was not found.") from exc

        try:
            verification = backup.perform_backup_verification(
                backup_run,
                requested_by_label=options["requested_by"],
                trigger_kind=options["trigger"],
                verification_run=verification_run,
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"verification run {verification.id} finished: {verification.status}"
            )
        )
