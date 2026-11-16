from __future__ import annotations

from datetime import date, timedelta

from . import canonical_population
from .runtime_shared import _parse_iso_date


def _runtime_module():
    from . import memorial_sheet_runtime

    return memorial_sheet_runtime


def build_memorial_sheet_context(
    source_id: str | None = None,
    household_id: str | None = None,
    person_id: str | None = None,
    data_backend: str = "db",
) -> dict:
    return _legacy_build_memorial_sheet_context(
        source_id=source_id,
        household_id=household_id,
        person_id=person_id,
        data_backend=data_backend,
    )


def _legacy_build_memorial_sheet_context(
    source_id: str | None = None,
    household_id: str | None = None,
    person_id: str | None = None,
    data_backend: str = "db",
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

    person = next(
        (row for row in detail["memorial_members"] if row["person_id"] == (person_id or "")),
        None,
    )
    if person is None:
        return {
            "available": False,
            "selected_source_id": active_source_id,
            "message": "指定した故人が見つかりませんでした。",
            "data_backend": dataset["data_backend"],
        }

    sheet = runtime._build_memorial_sheet_document(person)
    if sheet is None:
        return {
            "available": False,
            "selected_source_id": active_source_id,
            "message": "命日が入っていないため年忌表を計算できません。",
            "data_backend": dataset["data_backend"],
        }

    return {
        "available": True,
        "selected_source_id": active_source_id,
        "household": detail["summary"],
        "person": person,
        "sheet": sheet,
        "data_backend": dataset["data_backend"],
        "canonical_snapshot_id": canonical_snapshot_id,
    }


def _build_memorial_sheet_document(person: dict) -> dict | None:
    runtime = _runtime_module()
    death_date = _parse_iso_date(person.get("death_date_iso"))
    if death_date is None:
        return None
    homyo_display_text = runtime._memorial_sheet_display_homyo(person)
    return {
        "deceased": {
            "homyo": person.get("kaimyo", ""),
            "homyo_display_text": homyo_display_text,
            "homyo_display_parts": runtime._memorial_sheet_homyo_display_parts(homyo_display_text),
            "homyo_center_offset_em": runtime._memorial_sheet_homyo_center_offset_em(
                homyo_display_text
            ),
            "zokumyo": person.get("name", ""),
            "relationship": person.get("relationship", ""),
            "age_at_death": runtime._format_memorial_sheet_age_at_death(
                person.get("age_at_death", "")
            ),
            "age_unit": person.get("age_unit", "歳"),
        },
        "death_date_iso": death_date.isoformat(),
        "death_date_wareki": runtime._to_wareki_date(death_date),
        "kijitsu_rows": runtime._build_kijitsu_rows(death_date),
        "memorial_rows": runtime._build_memorial_sheet_rows(death_date),
    }


def _memorial_sheet_display_homyo(person: dict) -> str:
    homyo = str(person.get("kaimyo", "") or "").strip()
    if homyo:
        return homyo
    return str(person.get("name", "") or "").strip()


def _memorial_sheet_homyo_center_offset_em(display_text: str) -> float:
    normalized = "".join(str(display_text or "").split())
    if not normalized:
        return 0.0
    target_center_char_count = 4.5
    char_advance_em = 0.54
    raw_offset = (target_center_char_count - len(normalized)) * char_advance_em
    return round(max(-1.5, min(1.5, raw_offset)), 2)


def _memorial_sheet_homyo_display_parts(display_text: str) -> dict[str, str]:
    normalized = str(display_text or "").strip()
    for prefix in ("釋尼", "釈尼"):
        if normalized.startswith(prefix):
            return {
                "leading": prefix[0],
                "small": prefix[1],
                "trailing": normalized[2:],
            }
    return {
        "leading": normalized,
        "small": "",
        "trailing": "",
    }


def _format_memorial_sheet_age_at_death(value) -> str:
    runtime = _runtime_module()
    if value in (None, ""):
        return ""
    if isinstance(value, int):
        return runtime._to_kanji_number(value)

    text = str(value).strip()
    if not text:
        return ""
    normalized = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if normalized.isdigit():
        return runtime._to_kanji_number(int(normalized))
    return text


def _build_kijitsu_rows(death_date: date) -> list[dict]:
    runtime = _runtime_module()
    rows = []
    for step in runtime.KIJITSU_STEPS:
        target_date = death_date + timedelta(days=step["offset_days"])
        rows.append(
            {
                "label": step["label"],
                "month_day": runtime._format_month_day_kanji(target_date),
                "weekday": runtime.WEEKDAYS_JA[(target_date.weekday() + 1) % 7],
            }
        )
    return rows


def _build_memorial_sheet_rows(death_date: date) -> list[dict]:
    runtime = _runtime_module()
    rows = []
    for rank in runtime.MEMORIAL_RANKS:
        target_date = runtime.memorial_shared._add_memorial_years(death_date, rank)
        rows.append(
            {
                "rank": rank,
                "label": runtime._to_memorial_label(rank),
                "year_ad": target_date.year,
                "year_kanji": runtime._to_kanji_year_digits(target_date.year),
                "year_zenkaku": runtime._to_zenkaku_digits(target_date.year),
            }
        )
    return rows
