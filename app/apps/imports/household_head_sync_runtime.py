from __future__ import annotations

from django.db import transaction

from . import canonical_population, household_head_snapshot
from .models import Household, ImportBatch, Person
from .runtime_shared import _clean_value


def _runtime_module():
    from . import household_head_runtime

    return household_head_runtime


def sync_household_head_snapshot_from_person(
    *,
    household: Household,
    head_person: Person,
) -> list[str]:
    return household_head_snapshot.sync_household_head_snapshot_from_person(
        household=household,
        head_person=head_person,
    )


def sync_household_head_authority(
    source_id: str,
    *,
    batch: ImportBatch | None = None,
    dry_run: bool = False,
) -> dict:
    runtime = _runtime_module()
    target_batch = batch or canonical_population.canonical_provenance_import_batch(
        source_id=source_id,
    )
    summary = {
        "source_id": source_id,
        "batch_uuid": str(target_batch.batch_uuid) if target_batch is not None else "",
        "prepared_snapshot_id": target_batch.prepared_snapshot_id if target_batch is not None else "",
        "dry_run": dry_run,
        "household_count": 0,
        "created_head_person_count": 0,
        "created_head_person_households": [],
        "linked_head_person_count": 0,
        "linked_existing_head_person_count": 0,
        "synced_head_name_count": 0,
        "synced_head_name_kana_count": 0,
        "synced_snapshot_household_count": 0,
        "updated_household_count": 0,
        "unresolved_household_count": 0,
        "unresolved_households": [],
        "updated_households": [],
    }
    if target_batch is None:
        return summary

    def run_sync() -> dict:
        households = list(
            Household.objects.select_related("head_person")
            .filter(batch=target_batch, deleted_at__isnull=True)
            .order_by("household_uid")
        )
        summary["household_count"] = len(households)

        for household in households:
            resolved_head_person = household.resolve_head_person()
            created_head_person = False
            if resolved_head_person is None and _clean_value(household.snapshot_head_name()):
                if dry_run:
                    created_head_person = True
                else:
                    resolved_head_person = runtime.create_manual_household_head_person_from_snapshot(
                        household
                    )
                    created_head_person = resolved_head_person is not None
                if created_head_person:
                    summary["created_head_person_count"] += 1
                    summary["created_head_person_households"].append(household.household_uid)

            if resolved_head_person is None and not created_head_person:
                summary["unresolved_household_count"] += 1
                summary["unresolved_households"].append(
                    {
                        "household_id": household.household_uid,
                        "head_name": household.snapshot_head_name(),
                        "head_name_kana": household.snapshot_head_name_kana(),
                    }
                )
                continue

            person_name = (
                (resolved_head_person.name or "")
                if resolved_head_person is not None
                else _clean_value(household.snapshot_head_name())
            )
            person_kana = (
                (resolved_head_person.kana or "")
                if resolved_head_person is not None
                else _clean_value(household.snapshot_head_name_kana())
            )
            new_head_person_id = (
                resolved_head_person.person_uid if resolved_head_person is not None else "(new)"
            )
            update_fields: list[str] = []
            updated_row = {
                "household_id": household.household_uid,
                "head_person_id": new_head_person_id,
                "before_head_person_id": household.head_person.person_uid
                if household.head_person_id and household.head_person is not None
                else "",
                "before_head_name": household.snapshot_head_name(),
                "before_head_name_kana": household.snapshot_head_name_kana(),
                "person_name": person_name,
                "person_kana": person_kana,
                "created_head_person": created_head_person,
            }

            head_person_needs_link = created_head_person or (
                resolved_head_person is not None and household.head_person_id != resolved_head_person.pk
            )
            if head_person_needs_link:
                update_fields.append("head_person")
                summary["linked_head_person_count"] += 1
                if not created_head_person:
                    summary["linked_existing_head_person_count"] += 1
                if not dry_run and resolved_head_person is not None:
                    household.head_person = resolved_head_person
            if household.snapshot_head_name() != person_name:
                update_fields.append("raw_record")
                summary["synced_head_name_count"] += 1
                if not dry_run:
                    household.head_name = person_name
            if household.snapshot_head_name_kana() != person_kana:
                update_fields.append("raw_record")
                summary["synced_head_name_kana_count"] += 1
                if not dry_run:
                    household.head_name_kana = person_kana
            if "raw_record" in update_fields:
                summary["synced_snapshot_household_count"] += 1

            if not update_fields:
                continue

            summary["updated_household_count"] += 1
            summary["updated_households"].append(
                {
                    **updated_row,
                    "updated_fields": update_fields,
                }
            )
            if not dry_run:
                household.save(update_fields=[*dict.fromkeys(update_fields), "updated_at"])

        return summary

    if dry_run:
        return run_sync()

    with transaction.atomic():
        return run_sync()
