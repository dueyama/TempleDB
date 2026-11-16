from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.imports.import_batch_retirement_audit import build_retirement_audit
from apps.imports.models import ImportBatch


class Command(BaseCommand):
    help = (
        "Read-only, fail-closed audit before retiring Household, Person, and "
        "DeceasedProfile rows from import batches."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--batch-id",
            action="append",
            dest="batch_ids",
            required=True,
            type=int,
            help="ImportBatch id to audit. Pass multiple times to audit a set of batches.",
        )

    def handle(self, *args, **options) -> None:
        del args
        batch_ids = options.get("batch_ids") or []
        try:
            payload = build_retirement_audit(batch_ids)
        except (ImportBatch.DoesNotExist, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
