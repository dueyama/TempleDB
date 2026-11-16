from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import DatabaseBackupRun
from apps.core.services import tenant_operations_pack


class Command(BaseCommand):
    help = (
        "Export a verified product database and tenant-specific operational assets "
        "without source code or machine activation."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--backup-run-id", type=int, required=True)
        parser.add_argument("--output-root", type=Path, required=True)
        parser.add_argument("--confirm-installation-id", required=True)
        parser.add_argument(
            "--include-restricted-payload",
            action="store_true",
            help="Confirm that the archive contains database rows, credentials, and private assets.",
        )

    def handle(self, *args, **options) -> None:
        del args
        try:
            backup_run = DatabaseBackupRun.objects.get(pk=options["backup_run_id"])
            result = tenant_operations_pack.export_tenant_operations_pack(
                backup_run,
                output_root=options["output_root"],
                confirm_installation_id=options["confirm_installation_id"],
                include_restricted_payload=options["include_restricted_payload"],
            )
        except DatabaseBackupRun.DoesNotExist as exc:
            raise CommandError("指定したbackup runが見つかりません。") from exc
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "テナント運用パックを作成しました: "
                f"{result['archive_path']} "
                f"(size={result['archive_size']}, sha256={result['archive_sha256']})"
            )
        )
