from __future__ import annotations

from django.db.utils import OperationalError, ProgrammingError

from . import canonical_population, memorial_shared
from .browser_dataset_detail_builders import _build_household_browser_dataset_from_rows
from .browser_dataset_model_rows import _household_row_from_model, _person_row_from_model
from .browser_dataset_summary_builders import _build_household_browser_summary_dataset_from_rows
from .browser_virtual_heads import virtual_head_browser_metadata
from .models import Household, HouseholdProfile, Person, ServiceSchedule

LEGACY_IMPORTED_SCHEDULE_SOURCE_TABLES = memorial_shared.LEGACY_IMPORTED_SCHEDULE_SOURCE_TABLES


def _service_row_from_model(service: ServiceSchedule) -> dict[str, str]:
    from .service_ledger_runtime import (
        _service_row_from_model as _service_ledger_service_row_from_model,
    )

    return _service_ledger_service_row_from_model(service)


def _load_household_browser_rows_from_sqlite(
    source_id: str,
    snapshot_id: str,
    batch_id: int | None,
    *,
    canonical_population_checked: bool = False,
) -> dict | None:
    del snapshot_id, batch_id
    if not canonical_population_checked:
        canonical_population.canonical_provenance_import_batch(source_id=source_id)
    memorial_rules = memorial_shared._effective_memorial_rules([])
    schedule_type_labels = {}

    try:
        households = list(
            Household.objects.filter(deleted_at__isnull=True)
            .select_related("head_person")
            .order_by("household_uid")
        )
        household_profiles = {
            profile.household_uid: profile
            for profile in HouseholdProfile.objects.filter(
                source__source_id=source_id,
                household_uid__in=[row.legacy_household_id for row in households],
            ).select_related("district")
        }
        persons = list(
            Person.objects.filter(deleted_at__isnull=True)
            .select_related("household", "deceased_profile")
            .order_by("household__household_uid", "person_uid")
        )
        schedules = list(
            ServiceSchedule.objects.filter(
                deleted_at__isnull=True,
            )
            .exclude(
                record_origin=ServiceSchedule.Origin.IMPORTED,
                source_table__in=LEGACY_IMPORTED_SCHEDULE_SOURCE_TABLES,
            )
            .select_related("household", "person")
            .order_by("scheduled_date", "scheduled_time", "schedule_uid", "id")
        )
    except (OperationalError, ProgrammingError):
        return None

    schedule_rows: list[dict] = []
    bon_rows: list[dict] = []
    for schedule in schedules:
        row = _service_row_from_model(schedule)
        if schedule.source_table == "UTY020_初盆予定作成":
            bon_rows.append(row)
        else:
            schedule_rows.append(row)

    virtual_heads = virtual_head_browser_metadata(households)
    household_rows = []
    for household in households:
        row = _household_row_from_model(household, household_profiles.get(household.legacy_household_id))
        row["__virtual_head_browser"] = virtual_heads.get(household.household_uid, {})
        household_rows.append(row)
    return {
        "household_rows": household_rows,
        "person_rows": [_person_row_from_model(row) for row in persons],
        "schedule_rows": schedule_rows,
        "bon_rows": bon_rows,
        "memorial_rules": memorial_rules,
        "schedule_type_labels": schedule_type_labels,
    }


def _load_household_browser_dataset_from_sqlite(
    source_id: str,
    snapshot_id: str,
    batch_id: int | None,
    *,
    canonical_population_checked: bool = False,
) -> dict:
    from .browser_dataset_runtime_loaders import _empty_household_browser_dataset

    row_payload = _load_household_browser_rows_from_sqlite(
        source_id,
        snapshot_id,
        batch_id,
        canonical_population_checked=canonical_population_checked,
    )
    if row_payload is None:
        return _empty_household_browser_dataset()
    return _build_household_browser_dataset_from_rows(**row_payload)


def _load_household_browser_summary_dataset_from_sqlite(
    source_id: str,
    snapshot_id: str,
    batch_id: int | None,
    *,
    canonical_population_checked: bool = False,
) -> dict:
    from .browser_dataset_runtime_loaders import _empty_household_browser_summary_dataset

    row_payload = _load_household_browser_rows_from_sqlite(
        source_id,
        snapshot_id,
        batch_id,
        canonical_population_checked=canonical_population_checked,
    )
    if row_payload is None:
        return _empty_household_browser_summary_dataset()
    return _build_household_browser_summary_dataset_from_rows(**row_payload)
