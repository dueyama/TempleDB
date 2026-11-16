from __future__ import annotations

from apps.core.services import tenant_policy as tenant_policy_services

from . import memorial_shared
from .runtime_shared import _clean_value


def _memorial_notice_table_rows(columns: list[dict]) -> list[dict]:
    deceased_labels = tenant_policy_services.deceased_field_labels()
    table_labels = tenant_policy_services.memorial_notice_table_labels()
    return [
        {
            "label": table_labels["death_date"],
            "cell_kind": "date",
            "cells": [_split_notice_date_cell(column["target_date_wareki"]) for column in columns],
        },
        {
            "label": table_labels["memorial_service"],
            "cell_kind": "text",
            "cells": [column["label"] for column in columns],
        },
        {
            "label": deceased_labels["kaimyo"],
            "cell_kind": "text",
            "cells": [column["kaimyo"] for column in columns],
        },
        {
            "label": deceased_labels["zokumyo"],
            "cell_kind": "zokumyo",
            "cells": [_split_zokumyo_cell(column["zokumyo"]) for column in columns],
        },
        {
            "label": table_labels["other_note"],
            "cell_kind": "text",
            "cells": [column["other_note"] for column in columns],
        },
    ]


def _memorial_notice_table_entries(columns: list[dict]) -> list[dict]:
    entries: list[dict] = []
    for column in columns:
        zokumyo = _split_zokumyo_cell(column["zokumyo"])
        target_date = _split_notice_date_cell(column["target_date_wareki"])
        entries.append(
            {
                "row_kind": "entry",
                "target_date": column["target_date_wareki"],
                "target_date_year": target_date["year"],
                "target_date_main": target_date["month_day"],
                "label": column["label"],
                "kaimyo": column["kaimyo"],
                "zokumyo_name": zokumyo["name"],
                "zokumyo_age": zokumyo["age"],
                "other_note": column["other_note"],
            }
        )
    return entries


def _blank_memorial_notice_entry() -> dict:
    return {
        "row_kind": "blank",
        "target_date": "",
        "target_date_year": "",
        "target_date_main": "",
        "label": "",
        "kaimyo": "",
        "zokumyo_name": "",
        "zokumyo_age": "",
        "other_note": "",
        "reference_heading": "",
    }


def _reference_heading_memorial_notice_entry(reference_year: int) -> dict:
    entry = _blank_memorial_notice_entry()
    entry["row_kind"] = "reference_heading"
    entry["reference_heading"] = (
        f"（参考）翌年{reference_year}（{memorial_shared._to_wareki_year_numeric(reference_year)}）年の回忌法要予定"
    )
    return entry


def _pad_memorial_notice_entries(entries: list[dict], size: int) -> list[dict]:
    padded = list(entries)
    while len(padded) < size:
        padded.append(_blank_memorial_notice_entry())
    return padded


def _memorial_notice_zokumyo_text(candidate: dict) -> str:
    name = candidate.get("person_name", "")
    age_text = _memorial_notice_age_text(candidate.get("age_at_death", ""), candidate.get("age_unit", "歳"))
    if name and age_text:
        return f"{name}\n[small]{age_text}[/small]"
    return name or age_text


def _memorial_notice_age_text(age_at_death: str, age_unit: str) -> str:
    cleaned_age = _clean_value(age_at_death)
    if not cleaned_age:
        return ""
    return f"享年 {cleaned_age}{age_unit or '歳'}"


def _pad_memorial_notice_columns(columns: list[dict], size: int) -> list[dict]:
    padded = list(columns)
    while len(padded) < size:
        padded.append(_empty_memorial_notice_column())
    return padded


def _empty_memorial_notice_column() -> dict:
    return {
        "person_name": "",
        "kaimyo": "",
        "relationship": "",
        "target_date_iso": "",
        "target_date_wareki": "",
        "label": "",
        "zokumyo": "",
        "status_label": "",
        "other_note": "",
    }


def _split_notice_date_cell(value: str) -> dict:
    cleaned = _clean_value(value)
    if not cleaned:
        return {"year": "", "month_day": ""}
    if "年" in cleaned:
        era, remainder = cleaned.split("年", 1)
        return {"year": f"{era}年", "month_day": remainder}
    return {"year": "", "month_day": cleaned}


def _split_zokumyo_cell(value: str) -> dict:
    cleaned = _clean_value(value)
    if not cleaned:
        return {"name": "", "age": ""}
    if "\n[small]" in cleaned and cleaned.endswith("[/small]"):
        name, age = cleaned.split("\n[small]", 1)
        return {"name": name, "age": age.removesuffix("[/small]")}
    return {"name": cleaned, "age": ""}


__all__ = [
    "_blank_memorial_notice_entry",
    "_empty_memorial_notice_column",
    "_memorial_notice_age_text",
    "_memorial_notice_table_entries",
    "_memorial_notice_table_rows",
    "_memorial_notice_zokumyo_text",
    "_pad_memorial_notice_columns",
    "_pad_memorial_notice_entries",
    "_reference_heading_memorial_notice_entry",
    "_split_notice_date_cell",
    "_split_zokumyo_cell",
]
