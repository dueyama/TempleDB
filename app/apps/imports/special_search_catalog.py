from __future__ import annotations

from apps.core.services import tenant_policy

from .runtime_shared import _search_text

_SPECIAL_SEARCH_COPY = tenant_policy.terminology_copy()["special_search"]

SPECIAL_SEARCH_DEFINITIONS = [
    {
        "key": "data_quality",
        "label": "データ問題点",
        "description": _SPECIAL_SEARCH_COPY["data_quality_description"],
    },
    {
        "key": "auto_generated_kana",
        "label": "AI自動かな",
        "description": "かなを自動補完した人の一覧です。並び順確認や手修正の見直しに使います。",
    },
    {
        "key": "kaimyo_contains",
        "label": _SPECIAL_SEARCH_COPY["kaimyo_contains_label"],
        "description": _SPECIAL_SEARCH_COPY["kaimyo_contains_description"],
    },
    {
        "key": "memorial_notice_opt_out",
        "label": "年回案内不要",
        "description": "回忌案内に載せない故人の一覧です。",
    },
    {
        "key": "recent_deaths",
        "label": "最近の往生",
        "description": "過去1年ほどの往生者を確認します。",
    },
    {
        "key": "postal_non_head_recipient",
        "label": "戸主以外に郵送",
        "description": "送付区分が郵送で、戸主以外を送付先にしている家を確認します。",
    },
    {
        "key": "memorial_head_person",
        "label": "過去帳が戸主",
        "description": "戸主参照が過去帳の人を向いている家を確認します。",
    },
    {
        "key": "active_people_in_deleted_households",
        "label": "削除済み家に残る人",
        "description": "削除済み household に紐づいたまま未削除の人を確認します。",
    },
    {
        "key": "deleted_head_person_households",
        "label": "削除済み person が戸主",
        "description": "active household の戸主参照が削除済み person を向いている家を確認します。",
    },
    {
        "key": "legacy_schedules",
        "label": "旧予定",
        "description": "旧DBの予定明細から取り込まれた予定一覧です。不要な旧予定の確認に使います。",
    },
]


def _build_special_search_entries(
    search_key: str,
    dataset: dict,
    *,
    source_id: str | None = None,
    latest_batch=None,
    auto_generated_kana_builder,
    kaimyo_contains_builder,
    memorial_notice_opt_out_builder,
    recent_death_builder,
    postal_non_head_recipient_builder,
    memorial_head_person_builder,
    active_people_in_deleted_households_builder,
    deleted_head_person_households_builder,
    legacy_schedule_builder,
) -> list[dict]:
    if search_key == "auto_generated_kana":
        return auto_generated_kana_builder(dataset)
    if search_key == "kaimyo_contains":
        return kaimyo_contains_builder(dataset)
    if search_key == "memorial_notice_opt_out":
        return memorial_notice_opt_out_builder(dataset)
    if search_key == "recent_deaths":
        return recent_death_builder(dataset)
    if search_key == "postal_non_head_recipient":
        return postal_non_head_recipient_builder(
            source_id=source_id,
            latest_batch=latest_batch,
        )
    if search_key == "memorial_head_person":
        return memorial_head_person_builder(dataset)
    if search_key == "active_people_in_deleted_households":
        return active_people_in_deleted_households_builder(
            source_id=source_id,
            latest_batch=latest_batch,
        )
    if search_key == "deleted_head_person_households":
        return deleted_head_person_households_builder(
            source_id=source_id,
            latest_batch=latest_batch,
        )
    if search_key == "legacy_schedules":
        return legacy_schedule_builder(
            dataset,
            source_id=source_id,
            latest_batch=latest_batch,
        )
    return []


def _resolve_special_search_key(
    search_key: str | None,
    *,
    special_search_definitions: list[dict] | None = None,
) -> str:
    definitions = special_search_definitions or SPECIAL_SEARCH_DEFINITIONS
    valid_keys = {definition["key"] for definition in definitions}
    if search_key in valid_keys:
        return str(search_key)
    return definitions[0]["key"]


def _data_quality_total_count(context: dict) -> int:
    return sum(
        (
            context.get("same_name_group_count", 0),
            context.get("missing_death_date_count", 0),
            context.get("unknown_gender_count", 0),
            context.get("homyo_order_issue_count", 0),
            context.get("import_issue_total", 0),
        )
    )


def _special_search_entry_matches(entry: dict, needle: str, *, search_key: str | None = None) -> bool:
    if search_key == "kaimyo_contains":
        return needle in _search_text(entry.get("kaimyo"))
    return any(
        needle in _search_text(value)
        for value in (
            entry.get("household_id"),
            entry.get("household_name"),
            entry.get("person_id"),
            entry.get("person_name"),
            entry.get("kana"),
            entry.get("relationship"),
            entry.get("kaimyo"),
            entry.get("death_date"),
            entry.get("note"),
            entry.get("status_label"),
        )
    )
