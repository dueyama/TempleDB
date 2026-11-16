from __future__ import annotations

from .importer_parsing import (
    _clean_text,
    _has_deceased_profile_data,
    _is_deceased,
    _join_notes,
    _parse_boolean,
    _parse_int,
    _parse_legacy_date,
)
from .kana import normalize_kana_storage
from .models import ImportIssue, Person


def _create_issue(
    *,
    batch,
    stats: dict,
    severity: str,
    code: str,
    record: dict,
    legacy_pk_text: str,
    message: str,
    details: dict | None = None,
) -> None:
    ImportIssue.objects.create(
        batch=batch,
        severity=severity,
        code=code,
        source_table=record.get("source_table", ""),
        source_row_number=record.get("source_row_number"),
        legacy_pk_text=legacy_pk_text,
        message=message,
        details=details or {},
    )
    stats["issues_count"] += 1


def _import_person_rows(
    *,
    batch,
    source_entry: dict,
    prepared_snapshot: dict,
    table_paths: dict,
    households_by_legacy_id: dict,
    stats: dict,
) -> dict[str, Person]:
    from .importer_batch_lifecycle import _iter_jsonl

    source_mdb_file = str(source_entry["resolved_path"])
    source_export_batch = prepared_snapshot["snapshot_id"]
    persons_by_legacy_id: dict[str, Person] = {}
    for record in _iter_jsonl(table_paths["person_path"]):
        stats["records_read"] += 1
        values = record["values"]
        legacy_person_id = _clean_text(values.get("家族ID"))
        legacy_household_id = _clean_text(values.get("台帳ID"))
        if not legacy_person_id:
            _create_issue(
                batch=batch,
                stats=stats,
                severity=ImportIssue.Severity.ERROR,
                code="missing_person_id",
                record=record,
                legacy_pk_text="",
                message="UTB002_家族 row is missing 家族ID and was skipped.",
            )
            continue

        household = households_by_legacy_id.get(legacy_household_id)
        if household is None:
            stats["orphan_persons"] += 1
            _create_issue(
                batch=batch,
                stats=stats,
                severity=ImportIssue.Severity.ERROR,
                code="household_not_found",
                record=record,
                legacy_pk_text=legacy_person_id,
                message="UTB002_家族 row references a 台帳ID that was not imported into households.",
                details={"legacy_household_id": legacy_household_id},
            )
            continue

        birth_date_raw = _clean_text(values.get("生年月日"))
        birth_date = _parse_legacy_date(birth_date_raw)
        if birth_date.error:
            stats["birth_date_parse_errors"] += 1
            _create_issue(
                batch=batch,
                stats=stats,
                severity=ImportIssue.Severity.WARNING,
                code="birth_date_parse_error",
                record=record,
                legacy_pk_text=legacy_person_id,
                message=birth_date.error,
            )

        has_deceased_profile_data = _has_deceased_profile_data(values)
        death_date_raw = _clean_text(values.get("命日")) if has_deceased_profile_data else ""
        death_date = _parse_legacy_date(death_date_raw) if death_date_raw else _parse_legacy_date("")
        if death_date.error:
            stats["death_date_parse_errors"] += 1
            _create_issue(
                batch=batch,
                stats=stats,
                severity=ImportIssue.Severity.WARNING,
                code="death_date_parse_error",
                record=record,
                legacy_pk_text=legacy_person_id,
                message=death_date.error,
            )

        person = Person.objects.create(
            batch=batch,
            household=household,
            legacy_source_id=batch.source.source_id,
            source_mdb_file=source_mdb_file,
            source_export_batch=source_export_batch,
            source_table=record["source_table"],
            source_row_number=record["source_row_number"],
            legacy_pk_text=legacy_person_id,
            person_uid=legacy_person_id,
            legacy_household_id=legacy_household_id,
            name=_clean_text(values.get("氏名")),
            kana=normalize_kana_storage(_clean_text(values.get("ﾌﾘｶﾞﾅ"))),
            relationship_label=_clean_text(values.get("続柄")),
            family_category=_clean_text(values.get("家族区分")),
            gender=_clean_text(values.get("性別")),
            birth_date_raw=birth_date_raw,
            birth_date=birth_date.value,
            birth_date_parse_error=birth_date.error,
            person_note=_join_notes(values.get("個人備考"), values.get("故人備考")),
            is_deceased=_is_deceased(values),
            death_date_raw=death_date_raw,
            death_date=death_date.value,
            death_date_parse_error=death_date.error,
            kaimyo=_clean_text(values.get("戒名")) if has_deceased_profile_data else "",
            kaimyo_kana=(
                normalize_kana_storage(_clean_text(values.get("戒名ｶﾅ")))
                if has_deceased_profile_data
                else ""
            ),
            age_at_death_raw=_clean_text(values.get("享年")) if has_deceased_profile_data else "",
            age_at_death=_parse_int(values.get("享年")) if has_deceased_profile_data else None,
            age_unit=_clean_text(values.get("享年単位")) or "歳" if has_deceased_profile_data else "",
            legacy_hatsubon_flag=_clean_text(values.get("初盆")) if has_deceased_profile_data else "",
            hatsubon_flag=_parse_boolean(values.get("初盆")) if has_deceased_profile_data else None,
            memorial_notice_opt_out=(
                _parse_boolean(values.get("年回案内不要")) if has_deceased_profile_data else None
            ),
            deceased_note=_clean_text(values.get("故人備考")) if has_deceased_profile_data else "",
            memorial_payload=(
                {
                    "relationship": _clean_text(values.get("続柄")),
                    "legacy_household_id": legacy_household_id,
                }
                if has_deceased_profile_data
                else {}
            ),
            raw_record=values,
        )
        persons_by_legacy_id[legacy_person_id] = person
        stats["persons_imported"] += 1

        if has_deceased_profile_data:
            person.sync_legacy_deceased_profile()
            stats["deceased_profiles_imported"] += 1

    return persons_by_legacy_id
