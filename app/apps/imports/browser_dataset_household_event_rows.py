from __future__ import annotations

from . import browser_dataset_display, runtime_shared

_clean_value = runtime_shared._clean_value
_display_pairs = browser_dataset_display._display_pairs
_non_empty_pairs = browser_dataset_display._non_empty_pairs
_DISPLAY_COLUMN_RESERVE_KAIMYO = browser_dataset_display._DISPLAY_COLUMN_RESERVE_KAIMYO
_same_name_household_yuen_label = browser_dataset_display._same_name_household_yuen_label


def _is_yuen_household_row(row: dict) -> bool:
    yuen_label = _clean_value(row.get("__household_yuen_label"))
    if yuen_label:
        return yuen_label == "はい"
    return _same_name_household_yuen_label(
        row.get("__source_table"),
        row.get("氏名"),
    ) == "はい"


def _household_summary_sort_key(item: dict) -> tuple[int, str, str, int]:
    return (
        1 if item.get("is_yuen_household") else 0,
        runtime_shared._sort_text(item["kana"]),
        runtime_shared._sort_text(item["name"]),
        runtime_shared._int_sort(item["household_id"]),
    )


def _event_summary(row: dict, source_table: str, schedule_type_labels: dict[str, str]) -> dict:
    schedule_label = (
        row.get("予定種別名")
        or schedule_type_labels.get(row.get("予定種別ID", ""), "")
        or row.get("service_label", "")
    )
    summary = {
        "source_table": source_table,
        "event_id": row.get("予定ID", ""),
        "event_scope": row.get("__event_scope", "household"),
        "schedule_pk": row.get("__schedule_pk", ""),
        "scheduled_date": runtime_shared._display_value(row.get("予定年月日")),
        "completed_on": runtime_shared._display_value(row.get("実施日")),
        "target_date": runtime_shared._display_value(row.get("target_date")),
        "schedule_type": schedule_label,
        "subject_name": row.get("予備俗名") or row.get("予備戒名") or "",
        "note": row.get("予定備考", ""),
        "person_id": row.get("家族ID", ""),
        "status": runtime_shared._display_value(row.get("status")),
        "effective_status": runtime_shared._display_value(row.get("effective_status")),
        "status_label": runtime_shared._display_value(row.get("状態")),
        "record_origin": runtime_shared._display_value(row.get("record_origin")),
        "display_fields": _display_pairs(
            {
                "source_table": source_table,
                "予定ID": row.get("予定ID", ""),
                "予定種別名": schedule_label,
                "予定年月日": row.get("予定年月日", ""),
                "実施日": row.get("実施日", ""),
                "状態": row.get("状態", ""),
                "予定備考": row.get("予定備考", ""),
                "家族ID": row.get("家族ID", ""),
                "予備俗名": row.get("予備俗名", ""),
                _DISPLAY_COLUMN_RESERVE_KAIMYO: row.get("予備戒名", ""),
                "予備続柄": row.get("予備続柄", ""),
                "予備命日": row.get("予備命日", ""),
                "予備享年": runtime_shared._join_values(row.get("予備享年"), row.get("予備享年単位")),
                "法事場所": row.get("法事場所", ""),
                "お参り先氏名": row.get("お参り先氏名", ""),
                "お参り先住所1": row.get("お参り先住所1", ""),
                "お参り先電話": row.get("お参り先電話", ""),
            },
            [
                "source_table",
                "予定ID",
                "予定種別名",
                "予定年月日",
                "実施日",
                "状態",
                "予定備考",
                "家族ID",
                "予備俗名",
                _DISPLAY_COLUMN_RESERVE_KAIMYO,
                "予備続柄",
                "予備命日",
                "予備享年",
                "法事場所",
                "お参り先氏名",
                "お参り先住所1",
                "お参り先電話",
            ],
        ),
        "raw_fields": _non_empty_pairs({"source_table": source_table, **row}),
    }
    if summary["event_scope"] == "temple":
        labels = ["予定ID", "予定", "相手先", "予定年月日", "実施日", "状態", "場所", "メモ"]
        summary["display_fields"] = _display_pairs(
            {
                "予定ID": summary["event_id"],
                "予定": schedule_label,
                "相手先": summary["subject_name"],
                "予定年月日": summary["scheduled_date"],
                "実施日": summary["completed_on"],
                "状態": summary["status_label"],
                "場所": row.get("法事場所", ""),
                "メモ": summary["note"],
            },
            labels,
        )
    return summary
