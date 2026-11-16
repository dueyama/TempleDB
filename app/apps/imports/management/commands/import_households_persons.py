from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.imports.importers import import_households_persons
from apps.imports.legacy_reimport_guard import evaluate_legacy_reimport
from apps.imports.models import ImportBatch


class Command(BaseCommand):
    help = (
        "Import households/persons/deceased profiles/service schedules "
        "from raw JSONL into the canonical application database."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source-id",
            default=None,
            help=(
                "Source id from the runtime source registry "
                "(data/runtime/source_registry.json, with bootstrap fallback)."
            ),
        )
        parser.add_argument("--snapshot-id", default=None, help="Prepared/export snapshot id.")
        parser.add_argument(
            "--mode",
            choices=[ImportBatch.Mode.REHEARSAL, ImportBatch.Mode.FINAL],
            default=ImportBatch.Mode.REHEARSAL,
            help="Batch mode label.",
        )

    def handle(self, *args, **options) -> None:
        authorization = evaluate_legacy_reimport(options["source_id"])
        if not authorization.allowed:
            raise CommandError(authorization.message)
        try:
            batch = import_households_persons(
                source_id=authorization.source_id,
                snapshot_id=options["snapshot_id"],
                mode=options["mode"],
                expected_source_path=authorization.source_path,
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Imported batch "
                f"{batch.batch_uuid} "
                f"(households={batch.households_imported}, "
                f"persons={batch.persons_imported}, "
                f"deceased={batch.deceased_profiles_imported}, "
                f"services={batch.service_schedules_imported}, "
                f"issues={batch.issues_count})"
            )
        )
