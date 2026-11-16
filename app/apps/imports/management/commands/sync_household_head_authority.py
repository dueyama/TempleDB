from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.imports import household_head_runtime, source_runtime


class Command(BaseCommand):
    help = "Link household head authority to Person records and sync household head snapshots."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source-id",
            dest="source_id",
            default="",
            help="Legacy source id to sync. Defaults to the current resolved source.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Report planned changes without mutating records.",
        )

    def handle(self, *args, **options) -> None:
        requested_source_id = (options.get("source_id") or "").strip()
        source_id = source_runtime.resolve_source_entry(requested_source_id or None)["source_id"]
        summary = household_head_runtime.sync_household_head_authority(
            source_id,
            dry_run=bool(options.get("dry_run")),
        )
        self.stdout.write(
            json.dumps(
                summary,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
