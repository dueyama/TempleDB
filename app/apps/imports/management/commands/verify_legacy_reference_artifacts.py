from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.imports.legacy_reference_artifacts import (
    ArtifactVerificationError,
    verify_legacy_reference_artifacts,
)


class Command(BaseCommand):
    help = (
        "Verify one explicit Access/MDB adapter snapshot without changing files or the database."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--snapshot-id", required=True)
        parser.add_argument(
            "--exports-base",
            help="Alternative legacy_exports root, used together with --prepared-base.",
        )
        parser.add_argument(
            "--prepared-base",
            help="Alternative prepared_exports root, used together with --exports-base.",
        )

    def handle(self, *args, **options) -> None:
        del args
        exports_base = options.get("exports_base")
        prepared_base = options.get("prepared_base")
        if bool(exports_base) != bool(prepared_base):
            raise CommandError("--exports-base and --prepared-base must be specified together.")

        verify_options = {
            "source_id": options["source_id"],
            "snapshot_id": options["snapshot_id"],
        }
        if exports_base and prepared_base:
            verify_options.update(
                {
                    "exports_base": Path(exports_base),
                    "prepared_base": Path(prepared_base),
                }
            )
        try:
            payload = verify_legacy_reference_artifacts(
                **verify_options,
            )
        except ArtifactVerificationError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
