from __future__ import annotations

from .importer_parsing import _clean_text, _parse_legacy_household_notice_opt_out
from .models import Household, HouseholdProfile, ImportIssue


def _import_household_rows(
    *,
    batch,
    source_entry: dict,
    prepared_snapshot: dict,
    table_paths: dict,
    stats: dict,
) -> dict[str, Household]:
    from .importer_batch_lifecycle import _iter_jsonl
    from .importer_person_rows import _create_issue

    source_mdb_file = str(source_entry["resolved_path"])
    source_export_batch = prepared_snapshot["snapshot_id"]
    households_by_legacy_id: dict[str, Household] = {}
    for record in _iter_jsonl(table_paths["household_path"]):
        stats["records_read"] += 1
        values = record["values"]
        legacy_household_id = _clean_text(values.get("台帳ID"))
        if not legacy_household_id:
            _create_issue(
                batch=batch,
                stats=stats,
                severity=ImportIssue.Severity.ERROR,
                code="missing_household_id",
                record=record,
                legacy_pk_text="",
                message="UTB001_戸主 row is missing 台帳ID and was skipped.",
            )
            continue

        household = Household.objects.create(
            batch=batch,
            legacy_source_id=batch.source.source_id,
            source_mdb_file=source_mdb_file,
            source_export_batch=source_export_batch,
            source_table=record["source_table"],
            source_row_number=record["source_row_number"],
            legacy_pk_text=legacy_household_id,
            household_uid=legacy_household_id,
            postal_code=_clean_text(values.get("〒")),
            address_line1=_clean_text(values.get("住所1")),
            address_line2=_clean_text(values.get("住所2")),
            address_line3=_clean_text(values.get("住所3")),
            phone=_clean_text(values.get("電話")),
            fax=_clean_text(values.get("ＦＡＸ")),
            mobile=_clean_text(values.get("携帯")),
            email=_clean_text(values.get("Email")),
            steward_legacy_id=_clean_text(values.get("世話人ID")),
            ledger_category=_clean_text(values.get("台帳区分")),
            notes=_clean_text(values.get("備考")),
            raw_record=values,
        )
        households_by_legacy_id[legacy_household_id] = household
        stats["households_imported"] += 1

    _sync_household_notice_flags_from_legacy(
        source=batch.source,
        households=households_by_legacy_id.values(),
    )
    return households_by_legacy_id


def _sync_household_notice_flags_from_legacy(
    *,
    source,
    households,
) -> None:
    household_list = list(households)
    if not household_list:
        return
    existing_profiles = {
        profile.household_uid: profile
        for profile in HouseholdProfile.objects.filter(
            source=source,
            household_uid__in=[household.household_uid for household in household_list],
        )
    }
    for household in household_list:
        raw_record = household.raw_record if isinstance(household.raw_record, dict) else {}
        general_notice_opt_out = _parse_legacy_household_notice_opt_out(raw_record.get("案内要否"))
        memorial_notice_opt_out = _parse_legacy_household_notice_opt_out(raw_record.get("年回要否"))
        if not general_notice_opt_out and not memorial_notice_opt_out:
            continue
        profile = existing_profiles.get(household.household_uid)
        if profile is None:
            profile = HouseholdProfile(
                source=source,
                legacy_household_id=household.household_uid,
            )
            existing_profiles[household.household_uid] = profile
        changed = False
        if general_notice_opt_out and profile.general_notice_opt_out is None:
            profile.general_notice_opt_out = True
            changed = True
        if memorial_notice_opt_out and profile.memorial_notice_opt_out is None:
            profile.memorial_notice_opt_out = True
            changed = True
        if changed:
            profile.save()
