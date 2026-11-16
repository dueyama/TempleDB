from __future__ import annotations

import re
from datetime import date

from django.db.utils import OperationalError, ProgrammingError

from . import canonical_population, memorial_notice_columns, memorial_shared, service_ledger_runtime
from .models import ServiceSchedule
from .runtime_shared import _parse_iso_date

HOUSEHOLD_MEMORIAL_LIST_COMPLETION_ROW_WEIGHT = 0.65


def _runtime_module():
    from . import memorial_sheet_runtime

    return memorial_sheet_runtime


def build_household_memorial_list_context(
    source_id: str | None = None,
    household_id: str | None = None,
    data_backend: str = "db",
    start_date: str | date | None = None,
) -> dict:
    return _legacy_build_household_memorial_list_context(
        source_id=source_id,
        household_id=household_id,
        data_backend=data_backend,
        start_date=start_date,
    )


def _legacy_build_household_memorial_list_context(
    source_id: str | None = None,
    household_id: str | None = None,
    data_backend: str = "db",
    start_date: str | date | None = None,
) -> dict:
    del data_backend
    runtime = _runtime_module()
    requested_source_id = (source_id or "").strip() or None
    if requested_source_id is None:
        active_source_id = runtime.resolve_runtime_source_entry()["source_id"]
    else:
        active_source_id = requested_source_id
    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    if provenance_batch is None:
        return {
            "available": False,
            "selected_source_id": active_source_id,
            "message": "現行データがまだありません。",
            "data_backend": "db",
        }

    canonical_snapshot_id = provenance_batch.prepared_snapshot_id or ""
    dataset = runtime._load_household_browser_dataset(active_source_id, canonical_snapshot_id)
    detail = dataset["household_details"].get(household_id or "")
    if detail is None:
        return {
            "available": False,
            "selected_source_id": active_source_id,
            "message": "指定した家が見つかりませんでした。",
            "data_backend": dataset["data_backend"],
        }

    resolved_start_date = runtime._resolve_household_memorial_list_start_date(start_date)
    rows = runtime._build_household_memorial_list_rows(
        detail.get("memorial_members", []),
        start_date=resolved_start_date,
    )
    schedules = _load_household_memorial_list_schedules(household_id or "")
    rows = _decorate_household_memorial_list_completion(rows, schedules)
    pages = runtime._paginate_household_memorial_list_rows(rows)
    household_summary = {
        **detail["summary"],
        "name": runtime._household_memorial_list_display_name(detail["summary"].get("name", "")),
    }
    return {
        "available": True,
        "selected_source_id": active_source_id,
        "household": household_summary,
        "rows": rows,
        "row_count": len(rows),
        "entry_count": len(rows),
        "person_count": len({row.get("person_id", "") for row in rows if row.get("person_id", "")}),
        "page_count": len(pages),
        "pages": pages,
        "selected_start_date": resolved_start_date.isoformat(),
        "data_backend": dataset["data_backend"],
        "canonical_snapshot_id": canonical_snapshot_id,
    }


def _build_household_memorial_list_rows(
    memorial_members: list[dict],
    *,
    start_date: date | None = None,
) -> list[dict]:
    runtime = _runtime_module()
    threshold = start_date or date.today()
    entries = []
    for person in memorial_members:
        death_date = _parse_iso_date(person.get("death_date_iso"))
        if death_date is None:
            continue
        for rank in runtime.MEMORIAL_RANKS:
            target_date = runtime.memorial_shared._add_memorial_years(death_date, rank)
            if target_date < threshold:
                continue
            entries.append(
                {
                    "person_id": person.get("person_id", ""),
                    "name": runtime._household_memorial_list_display_name(person.get("name", "")),
                    "relationship": person.get("relationship", ""),
                    "kaimyo": person.get("kaimyo", ""),
                    "subline": runtime._household_memorial_list_subline(person),
                    "death_date": death_date.isoformat(),
                    "death_date_wareki": runtime._to_wareki_date(death_date),
                    "death_date_display": runtime._household_memorial_list_date_with_wareki_year(
                        death_date
                    ),
                    "memorial_label": runtime._to_memorial_label(rank),
                    "memorial_label_compact": runtime._household_memorial_list_compact_memorial_label(
                        rank
                    ),
                    "target_date": target_date.isoformat(),
                    "age_display": runtime._household_memorial_list_age_display(
                        person.get("age_at_death", ""),
                        person.get("age_unit", "歳"),
                    ),
                }
            )
    sorted_entries = sorted(
        entries,
        key=lambda item: (
            item.get("target_date", ""),
            str(item.get("name", "")),
            str(item.get("memorial_label", "")),
        ),
    )
    for index, item in enumerate(sorted_entries, start=1):
        item["index"] = index
    return sorted_entries


def _load_household_memorial_list_schedules(household_id: str) -> list[ServiceSchedule]:
    if not household_id:
        return []
    try:
        schedules = list(
            ServiceSchedule.objects.filter(
                household_uid=household_id,
                deleted_at__isnull=True,
            )
            .exclude(
                record_origin=ServiceSchedule.Origin.IMPORTED,
                source_table__in=memorial_shared.LEGACY_IMPORTED_SCHEDULE_SOURCE_TABLES,
            )
            .select_related("household", "person", "person__deceased_profile")
            .order_by("scheduled_date", "completed_on", "target_date", "id")
        )
    except (OperationalError, ProgrammingError):
        return []
    return [
        schedule
        for schedule in schedules
        if service_ledger_runtime._is_actual_service_schedule(schedule)
    ]


def _decorate_household_memorial_list_completion(
    rows: list[dict],
    schedules: list[ServiceSchedule],
) -> list[dict]:
    linked_schedules_by_group: dict[str, list[ServiceSchedule]] = {}
    for schedule in schedules:
        if schedule.link_group_key:
            linked_schedules_by_group.setdefault(schedule.link_group_key, []).append(schedule)

    decorated_rows: list[dict] = []
    for entry in rows:
        row = {
            **entry,
            "is_completed": False,
            "completion_status_label": "",
            "completion_note": "",
        }
        candidate = {
            **entry,
            "label": entry.get("memorial_label", ""),
        }
        matching_schedule = service_ledger_runtime._matching_actual_schedule_for_candidate(
            candidate,
            sorted(
                schedules,
                key=lambda schedule: _household_memorial_list_match_priority(
                    schedule,
                    candidate,
                ),
            ),
        )
        if (
            matching_schedule is not None
            and service_ledger_runtime._effective_service_schedule_status(matching_schedule)
            == ServiceSchedule.Status.COMPLETED
        ):
            target_date = _parse_iso_date(entry.get("target_date"))
            row.update(
                {
                    "is_completed": True,
                    "completion_status_label": "勤修済み",
                    "completion_note": memorial_notice_columns._memorial_notice_note(
                        matching_schedule,
                        target_date,
                        linked_schedules_by_group,
                    ),
                }
            )
        decorated_rows.append(row)
    return decorated_rows


def _household_memorial_list_match_priority(
    schedule: ServiceSchedule,
    candidate: dict,
) -> tuple:
    candidate_target_date = _parse_iso_date(candidate.get("target_date"))
    schedule_target_date = service_ledger_runtime._resolved_service_schedule_target_date(schedule)
    is_exact_target = (
        candidate_target_date is not None
        and schedule_target_date == candidate_target_date
    )
    is_completed = (
        service_ledger_runtime._effective_service_schedule_status(schedule)
        == ServiceSchedule.Status.COMPLETED
    )
    effective_date = schedule.completed_on or schedule.scheduled_date or date.max
    return (
        not is_exact_target,
        not is_completed,
        effective_date,
        schedule.pk or 0,
    )


def _resolve_household_memorial_list_start_date(value: str | date | None) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        parsed = _parse_iso_date(value.strip())
        if parsed is not None:
            return parsed
    return date.today()


def _household_memorial_list_subline(person: dict) -> str:
    return str(person.get("relationship", "") or "").strip()


def _household_memorial_list_age_display(age_at_death, age_unit: str) -> str:
    cleaned = str(age_at_death or "").strip()
    if not cleaned:
        return ""
    return f"{cleaned}{str(age_unit or '歳').strip()}"


def _household_memorial_list_date_with_wareki_year(target: date) -> str:
    runtime = _runtime_module()
    wareki_text = runtime._to_wareki_date_numeric(target)
    wareki_year = wareki_text.split("年", 1)[0].strip()
    if not wareki_year:
        return target.isoformat()
    return f"{target.isoformat()}（{wareki_year}）"


def _household_memorial_list_compact_memorial_label(rank: int) -> str:
    if rank == 1:
        return "一周忌"
    return f"{rank}回忌"


def _household_memorial_list_display_name(value) -> str:
    parts = [part for part in re.split(r"[ \u3000]+", str(value or "").strip()) if part]
    if not parts:
        return ""
    return "　".join(parts)


def _household_memorial_list_row_weight(entry: dict) -> float:
    runtime = _runtime_module()
    weight = 1.0
    compact_name = re.sub(r"[ \u3000]+", "", str(entry.get("name", "") or ""))
    if len(compact_name) >= runtime.HOUSEHOLD_MEMORIAL_LIST_LONG_NAME_THRESHOLD:
        weight += runtime.HOUSEHOLD_MEMORIAL_LIST_LONG_NAME_WEIGHT
    if len(str(entry.get("kaimyo", "") or "").strip()) >= runtime.HOUSEHOLD_MEMORIAL_LIST_LONG_KAIMYO_THRESHOLD:
        weight += runtime.HOUSEHOLD_MEMORIAL_LIST_LONG_KAIMYO_WEIGHT
    if str(entry.get("subline", "") or "").strip():
        weight += runtime.HOUSEHOLD_MEMORIAL_LIST_SUBLINE_ROW_WEIGHT
    if entry.get("is_completed"):
        weight += HOUSEHOLD_MEMORIAL_LIST_COMPLETION_ROW_WEIGHT
    return weight


def _paginate_household_memorial_list_rows(rows: list[dict]) -> list[dict]:
    runtime = _runtime_module()
    pages: list[dict] = []
    current_entries: list[dict] = []
    current_weight = 0.0

    for entry in rows:
        row_weight = runtime._household_memorial_list_row_weight(entry)
        if current_entries and current_weight + row_weight > runtime.HOUSEHOLD_MEMORIAL_LIST_PAGE_ROW_BUDGET:
            pages.append({"number": len(pages) + 1, "entries": current_entries})
            current_entries = []
            current_weight = 0.0
        current_entries.append(entry)
        current_weight += row_weight

    if current_entries:
        pages.append({"number": len(pages) + 1, "entries": current_entries})

    return pages
