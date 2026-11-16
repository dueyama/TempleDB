from __future__ import annotations

import json

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q, QuerySet

from apps.imports import source_runtime
from apps.imports.models import (
    DeceasedProfile,
    Household,
    ImportBatch,
    ImportIssue,
    MemoTagAssignment,
    OfferingPayment,
    Person,
    ServiceSchedule,
    SourceOperationLog,
    VisitNote,
)


class Command(BaseCommand):
    help = "Retire non-current import batches from the runtime source."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--batch-id",
            action="append",
            dest="batch_ids",
            required=True,
            help="ImportBatch id to retire. Pass multiple times to retire multiple old batches.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Apply the deletion. Without this flag the command runs in dry-run mode.",
        )

    def handle(self, *args, **options):
        del args
        runtime_source_id = source_runtime.runtime_source_id()
        execute = bool(options["execute"])
        raw_batch_ids = options.get("batch_ids") or []
        batch_ids = self._parse_batch_ids(raw_batch_ids)
        batches = list(
            ImportBatch.objects.select_related("source")
            .filter(pk__in=batch_ids)
            .order_by("id")
        )
        found_ids = {batch.id for batch in batches}
        missing_ids = [batch_id for batch_id in batch_ids if batch_id not in found_ids]
        if missing_ids:
            raise CommandError(f"ImportBatch not found: {', '.join(str(batch_id) for batch_id in missing_ids)}")

        for batch in batches:
            if batch.source.source_id != runtime_source_id:
                raise CommandError(
                    f"Only runtime source batches can be retired: {batch.id} -> {batch.source.source_id}"
                )
            current_batch = source_runtime.latest_succeeded_import_batch(batch.source.source_id)
            if current_batch is not None and current_batch.id == batch.id:
                raise CommandError(f"Current successful batch cannot be retired: {batch.id}")

        batch_summaries = [self._build_batch_summary(batch) for batch in batches]
        result = {
            "mode": "execute" if execute else "dry-run",
            "runtime_source_id": runtime_source_id,
            "batch_ids": [batch.id for batch in batches],
            "batches": batch_summaries,
            "total_records": sum(item["total_records"] for item in batch_summaries),
        }

        if execute:
            with transaction.atomic():
                for batch in batches:
                    self._delete_batch(batch)
            result["deleted"] = True
        else:
            result["deleted"] = False

        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))

    def _parse_batch_ids(self, values: list[str]) -> list[int]:
        parsed: list[int] = []
        for value in values:
            raw = (value or "").strip()
            if not raw:
                continue
            try:
                batch_id = int(raw)
            except ValueError as exc:
                raise CommandError(f"Invalid --batch-id: {raw}") from exc
            if batch_id not in parsed:
                parsed.append(batch_id)
        if not parsed:
            raise CommandError("At least one --batch-id is required.")
        return parsed

    def _build_batch_summary(self, batch: ImportBatch) -> dict:
        counts = {
            "service_schedules": ServiceSchedule.objects.filter(related_batch=batch).count(),
            "visit_notes": VisitNote.objects.filter(related_batch=batch).count(),
            "offering_payments": OfferingPayment.objects.filter(related_batch=batch).count(),
            "import_issues": ImportIssue.objects.filter(batch=batch).count(),
            "deceased_profiles": DeceasedProfile.objects.filter(person__batch=batch).count(),
            "persons": Person.objects.filter(batch=batch).count(),
            "households": Household.objects.filter(batch=batch).count(),
            "memo_tag_assignments": self._memo_tag_assignments(batch).count(),
            "source_operation_log_targets": SourceOperationLog.objects.filter(target_batch=batch).count(),
            "import_batches": 1,
        }
        return {
            "batch_id": batch.id,
            "snapshot_id": batch.prepared_snapshot_id,
            "status": batch.status,
            "counts": counts,
            "total_records": sum(counts.values()),
        }

    def _delete_batch(self, batch: ImportBatch) -> None:
        self._memo_tag_assignments(batch).delete()
        VisitNote.objects.filter(related_batch=batch).delete()
        OfferingPayment.objects.filter(related_batch=batch).delete()
        ServiceSchedule.objects.filter(related_batch=batch).delete()
        DeceasedProfile.objects.filter(person__batch=batch).delete()
        Person.objects.filter(batch=batch).delete()
        Household.objects.filter(batch=batch).delete()
        batch.delete()

    def _memo_tag_assignments(self, batch: ImportBatch) -> QuerySet[MemoTagAssignment]:
        target_query = Q(pk__in=[])
        targets = (
            (Household, Household.objects.filter(batch=batch).values("pk")),
            (Person, Person.objects.filter(batch=batch).values("pk")),
            (
                DeceasedProfile,
                DeceasedProfile.objects.filter(person__batch=batch).values("pk"),
            ),
            (
                ServiceSchedule,
                ServiceSchedule.objects.filter(related_batch=batch).values("pk"),
            ),
            (VisitNote, VisitNote.objects.filter(related_batch=batch).values("pk")),
            (
                OfferingPayment,
                OfferingPayment.objects.filter(related_batch=batch).values("pk"),
            ),
        )
        for model, object_ids in targets:
            target_query |= Q(
                content_type=ContentType.objects.get_for_model(model),
                object_id__in=object_ids,
            )
        return MemoTagAssignment.objects.filter(target_query)
