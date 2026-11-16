from __future__ import annotations

from datetime import date

from apps.core.services import memorial_dates


def _parse_input_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _add_memorial_years(death_date: date, memorial_years: int) -> date:
    return memorial_dates._add_memorial_years(death_date, memorial_years)


def _add_memorial_offset_years(death_date: date, offset_years: int) -> date:
    return memorial_dates._add_memorial_offset_years(death_date, offset_years)


def _memorial_offset_years_from_label(label: str | None) -> int | None:
    return memorial_dates._memorial_offset_years_from_label(label)


def _memorial_offset_years(memorial_rank: int) -> int:
    return memorial_dates._memorial_offset_years(memorial_rank)


def _first_obon_date(death_date: date) -> date:
    return memorial_dates._first_obon_date(death_date)


def _replace_year_clamped(original: date, target_year: int) -> date:
    return memorial_dates._replace_year_clamped(original, target_year)


def _to_wareki_date_numeric(target: date) -> str:
    return memorial_dates._to_wareki_date_numeric(target)


def _kijitsu_offset_days_from_label(label: str | None) -> int | None:
    return memorial_dates._kijitsu_offset_days_from_label(label)
