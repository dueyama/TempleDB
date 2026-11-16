from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.imports.models import LegacySource
from apps.office.services.annual_membership_fee_postal_scans import verify_postal_scan_files


class Command(BaseCommand):
    help = "Verify annual membership fee postal scan PDF/crop evidence files."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--source-id", default="", help="LegacySource.source_id to verify.")
        parser.add_argument("--year", type=int, default=None, help="Membership fee year to verify.")
        parser.add_argument(
            "--no-fail",
            action="store_true",
            help="Print issues without returning a command failure.",
        )

    def handle(self, *args, **options):
        source_id = (options.get("source_id") or "").strip()
        source = None
        if source_id:
            try:
                source = LegacySource.objects.get(source_id=source_id)
            except LegacySource.DoesNotExist as exc:
                raise CommandError(f"unknown source: {source_id}") from exc
        issues = verify_postal_scan_files(source_record=source, year=options.get("year"))
        if not issues:
            self.stdout.write(self.style.SUCCESS("postal scan evidence OK"))
            return
        for issue in issues:
            self.stdout.write(
                f"scan={issue.scan_id} kind={issue.kind} path={issue.storage_key}: {issue.message}"
            )
        if not options.get("no_fail"):
            raise CommandError(f"{len(issues)} postal scan evidence issue(s) found")
