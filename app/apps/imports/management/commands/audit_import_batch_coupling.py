from __future__ import annotations

import json
from collections import defaultdict

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db.models import Count, F, Q, QuerySet

from apps.imports.models import (
    DeceasedProfile,
    Household,
    ImportBatch,
    MemoTagAssignment,
    OfferingPayment,
    Person,
    ServiceSchedule,
    VisitNote,
)


def _source_table_breakdown(
    queryset: QuerySet,
    *,
    source_table_field: str,
    active_filter: Q,
) -> list[dict[str, int | str]]:
    rows = (
        queryset.values(source_table_field)
        .annotate(
            raw=Count("pk"),
            active=Count("pk", filter=active_filter),
        )
        .order_by(source_table_field)
    )
    return [
        {
            "source_table": str(row[source_table_field] or ""),
            "raw": int(row["raw"]),
            "active": int(row["active"]),
        }
        for row in rows
    ]


def _memo_tag_assignment_orphan_count() -> int:
    assignments_by_content_type: dict[int, list[int]] = defaultdict(list)
    for content_type_id, object_id in MemoTagAssignment.objects.values_list(
        "content_type_id",
        "object_id",
    ):
        assignments_by_content_type[int(content_type_id)].append(int(object_id))

    content_types = ContentType.objects.in_bulk(assignments_by_content_type)
    orphan_count = 0
    for content_type_id, object_ids in assignments_by_content_type.items():
        content_type = content_types.get(content_type_id)
        model = content_type.model_class() if content_type is not None else None
        if model is None:
            orphan_count += len(object_ids)
            continue

        existing_ids = set(
            model._base_manager.filter(pk__in=set(object_ids)).values_list("pk", flat=True)
        )
        orphan_count += sum(object_id not in existing_ids for object_id in object_ids)
    return orphan_count


class Command(BaseCommand):
    help = "Read-only audit of import-batch coupling and provenance consistency."

    def handle(self, *args, **options) -> None:
        del args, options
        batches = list(ImportBatch.objects.select_related("source").order_by("id"))
        payload = {
            "schema_version": 1,
            "read_only": True,
            "active_definitions": {
                "households": "deleted_at IS NULL",
                "persons": "deleted_at IS NULL",
                "deceased_profiles": "person.deleted_at IS NULL",
                "service_schedules": "deleted_at IS NULL",
            },
            "batch_count": len(batches),
            "batches": [self._batch_summary(batch) for batch in batches],
            "unassigned_related_batch": {
                "service_schedules": ServiceSchedule.objects.filter(related_batch__isnull=True).count(),
                "visit_notes": VisitNote.objects.filter(related_batch__isnull=True).count(),
                "offering_payments": OfferingPayment.objects.filter(related_batch__isnull=True).count(),
            },
            "integrity": {
                "person_household_batch_mismatches": Person.objects.exclude(
                    batch_id=F("household__batch_id")
                ).count(),
                "source_mismatches": self._source_mismatch_counts(),
                "memo_tag_assignment_orphans": _memo_tag_assignment_orphan_count(),
            },
        }
        self.stdout.write(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )

    def _batch_summary(self, batch: ImportBatch) -> dict:
        households = Household.objects.filter(batch=batch)
        persons = Person.objects.filter(batch=batch)
        deceased_profiles = DeceasedProfile.objects.filter(person__batch=batch)
        service_schedules = ServiceSchedule.objects.filter(related_batch=batch)

        return {
            "batch_id": batch.id,
            "batch_uuid": str(batch.batch_uuid),
            "source_id": batch.source.source_id,
            "snapshot_id": batch.prepared_snapshot_id,
            "mode": batch.mode,
            "status": batch.status,
            "counts": {
                "households": {
                    "raw": households.count(),
                    "active": households.filter(deleted_at__isnull=True).count(),
                },
                "persons": {
                    "raw": persons.count(),
                    "active": persons.filter(deleted_at__isnull=True).count(),
                },
                "deceased_profiles": {
                    "raw": deceased_profiles.count(),
                    "active": deceased_profiles.filter(person__deleted_at__isnull=True).count(),
                },
            },
            "source_table_breakdown": {
                "households": _source_table_breakdown(
                    households,
                    source_table_field="source_table",
                    active_filter=Q(deleted_at__isnull=True),
                ),
                "persons": _source_table_breakdown(
                    persons,
                    source_table_field="source_table",
                    active_filter=Q(deleted_at__isnull=True),
                ),
                "deceased_profiles": _source_table_breakdown(
                    deceased_profiles,
                    source_table_field="person__source_table",
                    active_filter=Q(person__deleted_at__isnull=True),
                ),
                "service_schedules": _source_table_breakdown(
                    service_schedules,
                    source_table_field="source_table",
                    active_filter=Q(deleted_at__isnull=True),
                ),
            },
            "related_batch_references": {
                "service_schedules": service_schedules.count(),
                "visit_notes": VisitNote.objects.filter(related_batch=batch).count(),
                "offering_payments": OfferingPayment.objects.filter(related_batch=batch).count(),
            },
        }

    def _source_mismatch_counts(self) -> dict[str, int]:
        return {
            "household_vs_batch": Household.objects.exclude(
                legacy_source_id=F("batch__source__source_id")
            ).count(),
            "person_vs_batch": Person.objects.exclude(
                legacy_source_id=F("batch__source__source_id")
            ).count(),
            "person_vs_household": Person.objects.exclude(
                legacy_source_id=F("household__legacy_source_id")
            ).count(),
            "service_schedule_vs_related_batch": ServiceSchedule.objects.filter(
                related_batch__isnull=False
            )
            .exclude(legacy_source_id=F("related_batch__source__source_id"))
            .count(),
            "visit_note_vs_related_batch": VisitNote.objects.filter(related_batch__isnull=False)
            .exclude(legacy_source_id=F("related_batch__source__source_id"))
            .count(),
            "offering_payment_vs_related_batch": OfferingPayment.objects.filter(
                related_batch__isnull=False
            )
            .exclude(legacy_source_id=F("related_batch__source__source_id"))
            .count(),
        }
