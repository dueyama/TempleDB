from __future__ import annotations

from datetime import date, timedelta

from django.db.models.fields.json import KeyTextTransform
from django.db.utils import OperationalError, ProgrammingError

from . import (
    browser_dataset_member_rows,
    browser_dataset_same_name,
    household_profile_runtime,
    special_search_batch_entries,
    special_search_dataset_entries,
)
from .data_science_analysis_homyo import _homyo_order_issue
from .models import (
    Household,
    ImportBatch,
    ImportIssue,
    Person,
    ServiceSchedule,
)
from .runtime_shared import (
    _clean_value,
    _display_value,
    _parse_iso_date,
    _same_name_key,
)

SPECIAL_SEARCH_KEYS = (
    "data_quality",
    "auto_generated_kana",
    "kaimyo_contains",
    "memorial_notice_opt_out",
    "recent_deaths",
    "postal_non_head_recipient",
    "memorial_head_person",
    "active_people_in_deleted_households",
    "deleted_head_person_households",
    "legacy_schedules",
)

_PERSON_COUNT_VALUE_FIELDS = (
    "id",
    "person_uid",
    "household_id",
    "household__household_uid",
    "household__head_person_id",
    "name",
    "kana",
    "kana_is_auto_generated",
    "relationship_label",
    "family_category",
    "gender",
    "death_date_raw",
    "death_date",
    "kaimyo",
    "kaimyo_kana",
    "age_at_death_raw",
    "age_at_death",
    "age_unit",
    "legacy_hatsubon_flag",
    "hatsubon_flag",
    "memorial_notice_opt_out",
    "deceased_note",
    "memorial_payload",
)

_RAW_COUNT_COLUMNS = {
    "raw_death_date": "命日",
    "raw_kaimyo": "戒名",
    "raw_age_at_death": "享年",
    "raw_age_unit": "享年単位",
    "raw_hatsubon": "初盆",
    "raw_memorial_notice_opt_out": "年回案内不要",
    "raw_deceased_note": "故人備考",
    "raw_memorial_year": "年回01",
    "raw_chuin": "中陰01",
}


def build_special_search_counts(
    *,
    source_id: str | None,
    latest_batch: ImportBatch | None,
) -> dict[str, int]:
    counts = {key: 0 for key in SPECIAL_SEARCH_KEYS}
    if not source_id or latest_batch is None:
        return counts

    try:
        person_values = list(
            Person.objects.filter(
                deleted_at__isnull=True,
                household__deleted_at__isnull=True,
            )
            .annotate(
                **{
                    alias: KeyTextTransform(column, "raw_record")
                    for alias, column in _RAW_COUNT_COLUMNS.items()
                }
            )
            .values(*_PERSON_COUNT_VALUE_FIELDS, *_RAW_COUNT_COLUMNS)
            .order_by("household__household_uid", "person_uid", "id")
        )
        member_rows = [
            member
            for values in person_values
            if (member := _count_member_from_values(values)) is not None
        ]
        counts.update(_person_search_counts(member_rows))
        counts["active_people_in_deleted_households"] = Person.objects.filter(
            deleted_at__isnull=True,
            household__deleted_at__isnull=False,
        ).count()
        counts["deleted_head_person_households"] = Household.objects.filter(
            deleted_at__isnull=True,
            head_person__isnull=False,
            head_person__deleted_at__isnull=False,
        ).count()
        counts["legacy_schedules"] = ServiceSchedule.objects.filter(
            deleted_at__isnull=True,
            record_origin=ServiceSchedule.Origin.IMPORTED,
        ).count()
        counts["data_quality"] += ImportIssue.objects.filter(
            batch=latest_batch,
        ).count()
    except (OperationalError, ProgrammingError):
        return {key: 0 for key in SPECIAL_SEARCH_KEYS}

    counts["postal_non_head_recipient"] = len(
        special_search_batch_entries._postal_non_head_recipient_candidates(
            source_id=source_id,
            latest_batch=latest_batch,
            canonical_population_checked=True,
        )
    )
    return counts


def _count_member_from_values(values: dict) -> dict | None:
    row = _count_row_from_values(values)
    if browser_dataset_member_rows._is_placeholder_person_row(row):
        return None
    memorial = browser_dataset_member_rows._is_memorial_person(row)
    death_date = _display_value(row.get("命日"))
    kaimyo = _clean_value(row.get("戒名"))
    name = _clean_value(row.get("氏名"))
    kana = _clean_value(row.get("ﾌﾘｶﾞﾅ"))
    return {
        "person_pk": values["id"],
        "person_id": _clean_value(row.get("家族ID")),
        "household_pk": values["household_id"],
        "household_id": _clean_value(row.get("台帳ID")),
        "head_person_pk": values["household__head_person_id"],
        "name": name,
        "kana": kana,
        "relationship": _clean_value(row.get("続柄")),
        "member_type": "memorial" if memorial else "current",
        "death_date": death_date,
        "kaimyo": kaimyo,
        "gender": _clean_value(row.get("性別")),
        "kana_is_auto_generated": (
            _clean_value(row.get("__kana_is_auto_generated")).lower() == "true"
        ),
        "memorial_notice_opt_out": household_profile_runtime._parse_legacy_boolish(
            row.get("年回案内不要", "")
        ),
        "same_name_key": _same_name_key(name, kana),
    }


def _count_row_from_values(values: dict) -> dict[str, str]:
    row = {
        column: _clean_value(values.get(alias))
        for alias, column in _RAW_COUNT_COLUMNS.items()
    }
    row["家族ID"] = values["person_uid"]
    row["台帳ID"] = values["household__household_uid"]
    row["氏名"] = values["name"]
    row["ﾌﾘｶﾞﾅ"] = values["kana"]
    row["続柄"] = values["relationship_label"]
    row["家族区分"] = values["family_category"]
    row["性別"] = values["gender"]
    row["__kana_is_auto_generated"] = (
        "true" if values["kana_is_auto_generated"] else ""
    )

    if _values_have_memorial_details(values):
        death_date = values["death_date"]
        row["命日"] = values["death_date_raw"] or (
            death_date.isoformat() if death_date else ""
        )
        row["戒名"] = values["kaimyo"]
        age_at_death = values["age_at_death"]
        row["享年"] = values["age_at_death_raw"] or (
            str(age_at_death) if age_at_death is not None else ""
        )
        row["享年単位"] = values["age_unit"]
        row["初盆"] = household_profile_runtime._legacy_bool_value(
            values["hatsubon_flag"],
            values["legacy_hatsubon_flag"],
        )
        row["年回案内不要"] = household_profile_runtime._legacy_bool_value(
            values["memorial_notice_opt_out"]
        )
        row["故人備考"] = values["deceased_note"]
    return row


def _values_have_memorial_details(values: dict) -> bool:
    return any(
        (
            values["death_date"],
            values["death_date_raw"],
            values["kaimyo"],
            values["kaimyo_kana"],
            values["age_at_death_raw"],
            values["age_at_death"] is not None,
            values["deceased_note"],
            values["hatsubon_flag"] is True,
            values["memorial_notice_opt_out"] is True,
            bool(values["memorial_payload"]),
        )
    )


def _person_search_counts(member_rows: list[dict]) -> dict[str, int]:
    today = special_search_dataset_entries._runtime_timezone().localdate()
    cutoff = today - timedelta(days=365)
    same_name_groups = browser_dataset_same_name._build_same_name_groups(member_rows)
    memorial_rows = [
        member
        for member in member_rows
        if member["member_type"] == "memorial"
    ]
    parsed_death_dates = {
        member["person_pk"]: _parse_iso_date(member["death_date"])
        for member in memorial_rows
    }
    data_quality_total = (
        len(same_name_groups)
        + sum(
            1
            for member in memorial_rows
            if not member["death_date"]
        )
        + sum(
            1
            for member in member_rows
            if member["gender"] not in {"男", "女"}
        )
        + sum(
            1
            for member in memorial_rows
            if _homyo_order_issue(member) is not None
        )
    )
    return {
        "data_quality": data_quality_total,
        "auto_generated_kana": sum(
            1
            for member in member_rows
            if member["kana_is_auto_generated"]
        ),
        "kaimyo_contains": sum(
            1
            for member in member_rows
            if member["kaimyo"]
        ),
        "memorial_notice_opt_out": sum(
            1
            for member in memorial_rows
            if member["memorial_notice_opt_out"]
        ),
        "recent_deaths": sum(
            1
            for death_date in parsed_death_dates.values()
            if _is_recent_death(death_date, cutoff=cutoff)
        ),
        "memorial_head_person": len(
            {
                member["household_pk"]
                for member in memorial_rows
                if member["person_pk"] == member["head_person_pk"]
            }
        ),
    }


def _is_recent_death(value: date | None, *, cutoff: date) -> bool:
    return value is not None and value >= cutoff
