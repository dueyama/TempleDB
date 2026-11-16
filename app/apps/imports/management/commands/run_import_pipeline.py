from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.imports import pipeline_runtime


class Command(BaseCommand):
    help = (
        "Run export -> profile -> raw-layer -> import_households_persons "
        "for the selected source and write progress into data/generated/import_runs/."
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
        parser.add_argument(
            "--actor",
            default="",
            help="Username of the operator who started the pipeline.",
        )

    def handle(self, *args, **options) -> None:
        payload = pipeline_runtime.execute_import_pipeline(
            source_id=options["source_id"],
            actor=options["actor"],
        )
        if payload.get("status") != "succeeded":
            raise CommandError(payload.get("summary", "Pipeline failed."))
        self.stdout.write(self.style.SUCCESS(payload.get("summary", "Pipeline completed.")))
