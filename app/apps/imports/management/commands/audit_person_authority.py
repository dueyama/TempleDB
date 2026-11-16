from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.imports import household_head_runtime, source_runtime


class Command(BaseCommand):
    help = "Audit person-authority drift for district officers, head snapshots, and mailing recipients."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source-id",
            dest="source_id",
            default="",
            help="Legacy source id to audit. Defaults to the current resolved source.",
        )

    def handle(self, *args, **options) -> None:
        requested_source_id = (options.get("source_id") or "").strip()
        source_id = source_runtime.resolve_source_entry(requested_source_id or None)["source_id"]
        summary = household_head_runtime.person_authority_audit(source_id)
        self.stdout.write(
            json.dumps(
                summary,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
