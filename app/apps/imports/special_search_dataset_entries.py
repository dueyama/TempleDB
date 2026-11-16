from __future__ import annotations

from datetime import timedelta

from apps.core.services import tenant_policy

from .quality_runtime_shared import _runtime_timezone
from .runtime_shared import (
    _clean_value,
    _int_sort,
    _parse_iso_date,
    _sort_text,
)


def _special_search_copy() -> dict:
    return tenant_policy.terminology_copy()["special_search"]


def _build_auto_generated_kana_search_entries(dataset: dict) -> list[dict]:
    return sorted(
        (
            {
                "household_id": member["household_id"],
                "household_name": member.get("household_name", ""),
                "person_id": member["person_id"],
                "person_name": member["name"],
                "kana": member.get("kana", ""),
                "relationship": member.get("relationship", ""),
                "kaimyo": member.get("kaimyo", ""),
                "death_date": member.get("death_date", ""),
                "age_at_death": member.get("age_at_death", ""),
                "age_unit": member.get("age_unit", "歳"),
                "note": member.get("note", ""),
                "status_label": "AI自動",
            }
            for detail in dataset["household_details"].values()
            for member in [*detail.get("current_members", []), *detail.get("memorial_members", [])]
            if member.get("kana_is_auto_generated", False)
        ),
        key=lambda item: (
            _sort_text(item["kana"]),
            _sort_text(item["person_name"]),
            _sort_text(item["household_name"]),
            _int_sort(item["household_id"]),
            _int_sort(item["person_id"]),
        ),
    )


def _build_kaimyo_contains_search_entries(dataset: dict) -> list[dict]:
    special_search_copy = _special_search_copy()
    return sorted(
        (
            {
                "household_id": member["household_id"],
                "household_name": member.get("household_name", ""),
                "person_id": member["person_id"],
                "person_name": member["name"],
                "kana": member.get("kana", ""),
                "relationship": member.get("relationship", ""),
                "kaimyo": member.get("kaimyo", ""),
                "death_date": member.get("death_date", ""),
                "age_at_death": member.get("age_at_death", ""),
                "age_unit": member.get("age_unit", "歳"),
                "note": member.get("note", ""),
                "status_label": special_search_copy["kaimyo_match_status"],
            }
            for detail in dataset["household_details"].values()
            for member in [*detail.get("current_members", []), *detail.get("memorial_members", [])]
            if _clean_value(member.get("kaimyo"))
        ),
        key=lambda item: (
            _sort_text(item["kaimyo"]),
            _sort_text(item["person_name"]),
            _sort_text(item["household_name"]),
            _int_sort(item["household_id"]),
            _int_sort(item["person_id"]),
        ),
    )


def _build_memorial_notice_opt_out_search_entries(dataset: dict) -> list[dict]:
    return sorted(
        (
            {
                "household_id": member["household_id"],
                "household_name": member.get("household_name", ""),
                "person_id": member["person_id"],
                "person_name": member["name"],
                "kana": member.get("kana", ""),
                "relationship": member.get("relationship", ""),
                "kaimyo": member.get("kaimyo", ""),
                "death_date": member.get("death_date", ""),
                "age_at_death": member.get("age_at_death", ""),
                "age_unit": member.get("age_unit", "歳"),
                "note": member.get("note", ""),
                "status_label": "年回案内不要",
            }
            for detail in dataset["household_details"].values()
            for member in detail["memorial_members"]
            if member.get("memorial_notice_opt_out", False)
        ),
        key=lambda item: (
            _sort_text(item["person_name"]),
            _sort_text(item["household_name"]),
            _int_sort(item["household_id"]),
            _int_sort(item["person_id"]),
        ),
    )


def _build_recent_death_search_entries(dataset: dict) -> list[dict]:
    today = _runtime_timezone().localdate()
    cutoff = today - timedelta(days=365)
    entries = []
    for detail in dataset["household_details"].values():
        for member in detail["memorial_members"]:
            death_date = _parse_iso_date(member.get("death_date_iso"))
            if death_date is None or death_date < cutoff:
                continue
            entries.append(
                {
                    "household_id": member["household_id"],
                    "household_name": member.get("household_name", ""),
                    "person_id": member["person_id"],
                    "person_name": member["name"],
                    "kana": member.get("kana", ""),
                    "relationship": member.get("relationship", ""),
                    "kaimyo": member.get("kaimyo", ""),
                    "death_date": member.get("death_date", ""),
                    "age_at_death": member.get("age_at_death", ""),
                    "age_unit": member.get("age_unit", "歳"),
                    "note": member.get("note", ""),
                    "status_label": "過去1年",
                }
            )
    return sorted(
        entries,
        key=lambda item: (
            _sort_text(item["death_date"]),
            _sort_text(item["person_name"]),
            _sort_text(item["household_name"]),
            _int_sort(item["household_id"]),
            _int_sort(item["person_id"]),
        ),
        reverse=True,
    )


def _build_memorial_head_person_search_entries(dataset: dict) -> list[dict]:
    entries = []
    for detail in dataset.get("household_details", {}).values():
        head_person_id = _clean_value(detail.get("head_person_id"))
        if not head_person_id:
            continue
        memorial_head = next(
            (
                member
                for member in detail.get("memorial_members", [])
                if _clean_value(member.get("person_id")) == head_person_id
            ),
            None,
        )
        if memorial_head is None:
            continue
        summary = detail.get("summary")
        if not isinstance(summary, dict):
            summary = {}
        current_count = summary.get("current_count")
        if not isinstance(current_count, int):
            current_count = len(detail.get("current_members", []))
        memorial_count = summary.get("memorial_count")
        if not isinstance(memorial_count, int):
            memorial_count = len(detail.get("memorial_members", []))
        note_bits = [
            "戸主参照が過去帳",
            f"家の構成: 現在帳 {current_count} 人 / 過去帳 {memorial_count} 人",
        ]
        entries.append(
            {
                "household_id": memorial_head["household_id"],
                "household_name": memorial_head.get("household_name", "") or _clean_value(summary.get("name")),
                "person_id": memorial_head["person_id"],
                "person_name": memorial_head["name"],
                "kana": memorial_head.get("kana", ""),
                "relationship": memorial_head.get("relationship", ""),
                "kaimyo": memorial_head.get("kaimyo", ""),
                "death_date": memorial_head.get("death_date", ""),
                "age_at_death": memorial_head.get("age_at_death", ""),
                "age_unit": memorial_head.get("age_unit", "歳"),
                "note": " / ".join(note_bits),
                "status_label": "過去帳が戸主",
            }
        )
    return sorted(
        entries,
        key=lambda item: (
            _sort_text(item["person_name"]),
            _sort_text(item["household_name"]),
            _int_sort(item["household_id"]),
            _int_sort(item["person_id"]),
        ),
    )
