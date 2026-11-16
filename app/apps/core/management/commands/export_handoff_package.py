from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.services import handoff_package


class Command(BaseCommand):
    help = (
        "Export an allowlisted internal AI-maintenance handoff without "
        "operational database rows."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--output-root",
            default=None,
            help="Private 0700 destination. Defaults to data/generated/handoff_packages.",
        )

    def handle(self, *args, **options) -> None:
        del args
        try:
            manifest = handoff_package.export_handoff_package(
                output_root=Path(options["output_root"]) if options["output_root"] else None,
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "AI maintenance handoff written to "
                f"{manifest['archive_path']} "
                f"(sha256={manifest['archive_sha256']})."
            )
        )
