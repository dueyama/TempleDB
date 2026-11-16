from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.imports import kana_cleanup_runtime, source_runtime


class Command(BaseCommand):
    help = "Normalize business kana storage to full-width hiragana for the runtime source."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source-id",
            dest="source_id",
            default="",
            help="Optional source id. Only the runtime source is allowed.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            dest="execute",
            help="Apply the normalization. Without this flag the command runs in dry-run mode.",
        )

    def handle(self, *args, **options) -> None:
        del args
        requested_source_id = (options.get("source_id") or "").strip()
        if requested_source_id and requested_source_id != source_runtime.runtime_source_id():
            raise CommandError("Only the runtime source can be normalized.")
        summary = kana_cleanup_runtime.normalize_runtime_kana_storage(
            source_id=requested_source_id or None,
            dry_run=not bool(options.get("execute")),
        )
        self.stdout.write(
            json.dumps(
                summary,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
