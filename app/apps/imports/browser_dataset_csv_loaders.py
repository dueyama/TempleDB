from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from . import memorial_shared, runtime_shared
from .browser_dataset_detail_builders import _build_household_browser_dataset_from_rows


def _browser_table_paths(latest_export: dict) -> dict[str, Path]:
    table_paths = {}
    for row in latest_export["manifest"].get("tables", []):
        table_paths[row["table_name"]] = latest_export["snapshot_dir"] / row["csv_file"]
    return table_paths


@lru_cache(maxsize=8)
def _load_household_browser_dataset_from_csv(source_id: str, snapshot_id: str) -> dict:
    from .browser_dataset_runtime_loaders import (
        _empty_household_browser_dataset,
        _latest_export_snapshot,
    )
    from .household_memorial_candidates_runtime import _read_csv_rows

    latest_export = _latest_export_snapshot(source_id)
    if latest_export is None or latest_export["snapshot_id"] != snapshot_id:
        return _empty_household_browser_dataset()

    table_paths = _browser_table_paths(latest_export)
    memorial_rules = memorial_shared._effective_memorial_rules([])
    schedule_type_labels = _load_schedule_type_labels_from_table_paths(table_paths)
    return _build_household_browser_dataset_from_rows(
        household_rows=_read_csv_rows(table_paths.get("UTB001_戸主")),
        person_rows=_read_csv_rows(table_paths.get("UTB002_家族")),
        schedule_rows=_read_csv_rows(table_paths.get("UTM010_予定明細")),
        bon_rows=_read_csv_rows(table_paths.get("UTY020_初盆予定作成")),
        memorial_rules=memorial_rules,
        schedule_type_labels=schedule_type_labels,
    )


def _load_schedule_type_labels_from_table_paths(table_paths: dict[str, Path]) -> dict[str, str]:
    return {
        row["予定種別ID"]: row["予定名称"]
        for row in runtime_shared._read_csv_rows(table_paths.get("UTM001_予定種別"))
        if row.get("予定種別ID")
    }


def _load_memorial_rules_from_table_paths(table_paths: dict[str, Path]) -> list[dict]:
    return sorted(
        (
            {
                "years": int(row["回忌年"]),
                "label": row.get("回忌名", ""),
                "seq": runtime_shared._int_sort(row.get("SEQ")),
            }
            for row in runtime_shared._read_csv_rows(table_paths.get("MTC001_回忌"))
            if row.get("回忌年", "").isdigit()
        ),
        key=lambda item: (item["seq"], item["years"]),
    )
