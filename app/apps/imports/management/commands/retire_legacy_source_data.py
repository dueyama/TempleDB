from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from apps.imports.legacy_source_retirement import (
    LegacySourceRetirementError,
    build_legacy_source_retirement_plan,
    execute_legacy_source_retirement,
)


class Command(BaseCommand):
    help = (
        "Build a fail-closed plan for deleting one retired legacy source, or execute "
        "that exact plan after explicit hash confirmation and removal from the runtime "
        "source registry."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--source-id", required=True)
        parser.add_argument(
            "--expect-batch-id",
            action="append",
            dest="expected_batch_ids",
            type=int,
            help=(
                "Expected ImportBatch id. Repeat for every batch owned by the source. "
                "Required with --execute."
            ),
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Apply the exact dry-run plan confirmed by --confirm-plan.",
        )
        parser.add_argument(
            "--confirm-plan",
            default="",
            help="SHA256 plan hash printed by the immediately preceding dry-run.",
        )

    def handle(self, *args, **options) -> None:
        del args
        source_id = (options["source_id"] or "").strip()
        expected_batch_ids = options.get("expected_batch_ids") or []
        execute = bool(options["execute"])
        confirm_plan = (options.get("confirm_plan") or "").strip().lower()
        if not source_id:
            raise CommandError("--source-id is required.")
        if confirm_plan and not execute:
            raise CommandError("--confirm-plan can only be used with --execute.")

        try:
            if execute:
                payload = execute_legacy_source_retirement(
                    source_id,
                    expected_batch_ids=expected_batch_ids,
                    confirm_plan=confirm_plan,
                )
            else:
                payload = build_legacy_source_retirement_plan(
                    source_id,
                    expected_batch_ids=(expected_batch_ids or None),
                )
                payload["mode"] = "dry-run"
        except LegacySourceRetirementError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            json.dumps(
                payload,
                cls=DjangoJSONEncoder,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
