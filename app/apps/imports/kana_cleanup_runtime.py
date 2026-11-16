from __future__ import annotations

from django.db import transaction
from django.db.models import Count

from . import canonical_population
from .kana import normalize_kana_storage
from .models import Household, Person, ServiceSchedule
from .source_runtime import runtime_source_id


def normalize_runtime_kana_storage(
    *,
    source_id: str | None = None,
    dry_run: bool = True,
) -> dict:
    requested_source_id = (source_id or "").strip()
    resolved_source_id = runtime_source_id()
    if requested_source_id and requested_source_id != resolved_source_id:
        raise ValueError(
            f"Only the runtime source can be normalized: {requested_source_id} != {resolved_source_id}"
        )

    summary = {
        "mode": "dry-run" if dry_run else "execute",
        "source_id": resolved_source_id,
        "runtime_source_id": resolved_source_id,
        "visible_batch_id": None,
        "visible_snapshot_id": "",
        "counts": {
            "persons": 0,
        },
        "total_updates": 0,
    }

    def run_normalization() -> dict:
        visible_batch = canonical_population.canonical_provenance_import_batch(
            source_id=resolved_source_id,
        )
        if visible_batch is None:
            return summary
        summary["visible_batch_id"] = visible_batch.id
        summary["visible_snapshot_id"] = visible_batch.prepared_snapshot_id or ""

        households = list(Household.objects.filter(batch=visible_batch).order_by("id"))
        visible_household_ids = [household.household_uid for household in households]
        del visible_household_ids
        persons = list(Person.objects.filter(batch=visible_batch).order_by("id"))
        for person in persons:
            normalized = normalize_kana_storage(person.kana)
            if person.kana == normalized:
                continue
            summary["counts"]["persons"] += 1
            if not dry_run:
                person.kana = normalized
                person.save(update_fields=["kana", "updated_at"])

        summary["total_updates"] = sum(summary["counts"].values())
        return summary

    if dry_run:
        return run_normalization()

    with transaction.atomic():
        return run_normalization()


def _format_kana_normalization_summary(summary: dict) -> str:
    counts = summary.get("counts") or {}
    return f"{summary.get('mode', 'dry-run')}: persons {counts.get('persons', 0)} / total {summary.get('total_updates', 0)}"


def cleanup_runtime_manual_candidate_schedules(
    *,
    source_id: str | None = None,
    dry_run: bool = True,
    actor: str = "",
) -> dict:
    requested_source_id = (source_id or "").strip()
    resolved_source_id = runtime_source_id()
    if requested_source_id and requested_source_id != resolved_source_id:
        raise ValueError(
            f"Only the runtime source can be cleaned up: {requested_source_id} != {resolved_source_id}"
        )

    summary = {
        "mode": "dry-run" if dry_run else "execute",
        "source_id": resolved_source_id,
        "runtime_source_id": resolved_source_id,
        "visible_batch_id": None,
        "visible_snapshot_id": "",
        "counts": {
            "candidates": 0,
            "deletable": 0,
            "blocked": 0,
            "deleted": 0,
        },
        "deletable_ids": [],
        "blocked_ids": [],
    }

    def run_cleanup() -> dict:
        visible_batch = canonical_population.canonical_provenance_import_batch(
            source_id=resolved_source_id,
        )
        if visible_batch is None:
            return summary
        summary["visible_batch_id"] = visible_batch.id
        summary["visible_snapshot_id"] = visible_batch.prepared_snapshot_id or ""

        schedules = list(
            ServiceSchedule.objects.filter(
                related_batch=visible_batch,
                deleted_at__isnull=True,
                record_origin=ServiceSchedule.Origin.MANUAL,
                source_table="manual_service_schedule",
                status=ServiceSchedule.Status.CANDIDATE,
                scheduled_date__isnull=True,
                completed_on__isnull=True,
            )
            .annotate(
                payment_count=Count("offering_payments", distinct=True),
                visit_note_count=Count("visit_notes", distinct=True),
            )
            .order_by("household_uid", "person_uid", "id")
        )
        summary["counts"]["candidates"] = len(schedules)
        deletable: list[ServiceSchedule] = []
        for schedule in schedules:
            blocked = bool(
                getattr(schedule, "payment_count", 0)
                or getattr(schedule, "visit_note_count", 0)
                or (schedule.notes or "").strip()
            )
            if blocked:
                summary["counts"]["blocked"] += 1
                summary["blocked_ids"].append(schedule.schedule_uid or str(schedule.pk))
                continue
            summary["counts"]["deletable"] += 1
            summary["deletable_ids"].append(schedule.schedule_uid or str(schedule.pk))
            deletable.append(schedule)

        if not dry_run:
            for schedule in deletable:
                schedule.mark_deleted(
                    editor_label=actor,
                    note="未設定の手入力法要残骸を一括整理",
                )
                schedule.save(
                    update_fields=[
                        "deleted_at",
                        "deleted_by",
                        "deletion_note",
                        "updated_at",
                    ]
                )
                summary["counts"]["deleted"] += 1
        return summary

    if dry_run:
        return run_cleanup()

    with transaction.atomic():
        return run_cleanup()


def _format_manual_candidate_cleanup_summary(summary: dict) -> str:
    counts = summary.get("counts") or {}
    return (
        f"{summary.get('mode', 'dry-run')}: candidates {counts.get('candidates', 0)}"
        f" / deletable {counts.get('deletable', 0)}"
        f" / blocked {counts.get('blocked', 0)}"
        f" / deleted {counts.get('deleted', 0)}"
    )
