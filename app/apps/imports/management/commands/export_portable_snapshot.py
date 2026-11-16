from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.imports.exporters import export_portable_snapshot


class Command(BaseCommand):
    help = (
        "Export the latest succeeded operational batch as CSV/JSONL so it can be "
        "moved to another database product later."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source-id",
            default=None,
            help="Limit export selection to one source id. Defaults to the latest succeeded batch overall.",
        )
        parser.add_argument(
            "--batch-uuid",
            default=None,
            help="Export a specific import batch instead of the latest succeeded batch.",
        )
        parser.add_argument(
            "--output-root",
            default=None,
            help="Destination root. Defaults to data/generated/portable_exports.",
        )

    def handle(self, *args, **options) -> None:
        output_root = options["output_root"]
        try:
            manifest = export_portable_snapshot(
                source_id=options["source_id"],
                batch_uuid=options["batch_uuid"],
                output_root=Path(output_root) if output_root else None,
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Portable export written to {manifest['output_dir']} "
                f"(batch {manifest['batch_uuid']})."
            )
        )
