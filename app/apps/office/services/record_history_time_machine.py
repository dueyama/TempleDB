from __future__ import annotations

import json

from apps.imports.models import RecordEditLog

from .record_history_feed import _history_field_changes, _record_field_change_rows
from .record_history_snapshot import _normalize_snapshot_value, _snapshot_value

TIME_MACHINE_FIELD_SPECS = {
    RecordEditLog.RecordType.HOUSEHOLD: {
        "head_person_name": {"paths": ["head_name"]},
        "head_person_kana": {"paths": ["head_name_kana"]},
        "head_gender": {"paths": ["head_gender"]},
        "postal_code": {"paths": ["postal_code"]},
        "address_line1": {"paths": ["address_line1"]},
        "address_line2": {"paths": ["address_line2"]},
        "address_line3": {"paths": ["address_line3"]},
        "phone": {"paths": ["phone"]},
        "fax": {"paths": ["fax"]},
        "mobile": {"paths": ["mobile"]},
        "email": {"paths": ["email"]},
        "delivery_method": {"paths": ["household_profile.delivery_method"]},
        "household_general_notice_opt_out": {"paths": ["household_profile.general_notice_opt_out"]},
        "household_memorial_notice_opt_out": {"paths": ["household_profile.memorial_notice_opt_out"]},
        "district_id": {
            "paths": ["household_profile.district_id"],
            "display_paths": ["household_profile.district_name", "household_profile.district_id"],
        },
        "ledger_category": {"paths": ["ledger_category"]},
        "notes": {"paths": ["notes"]},
    },
    RecordEditLog.RecordType.PERSON: {
        "name": {"paths": ["name"]},
        "kana": {"paths": ["kana"]},
        "relationship_label": {"paths": ["relationship_label"]},
        "family_category": {"paths": ["family_category"]},
        "gender": {"paths": ["gender"]},
        "is_district_officer": {"paths": ["is_district_officer"]},
        "is_responsible_officer": {"paths": ["is_responsible_officer"]},
        "is_monto_sodai": {"paths": ["is_monto_sodai"]},
        "birth_date_input": {"paths": ["birth_date_raw", "birth_date"]},
        "person_note": {"paths": ["person_note"]},
        "death_date_input": {"paths": ["deceased_profile.death_date_raw", "deceased_profile.death_date"]},
        "kaimyo": {"paths": ["deceased_profile.kaimyo"]},
        "kaimyo_kana": {"paths": ["deceased_profile.kaimyo_kana"]},
        "age_at_death": {"paths": ["deceased_profile.age_at_death"]},
        "age_unit": {"paths": ["deceased_profile.age_unit"]},
        "hatsubon_flag": {"paths": ["deceased_profile.hatsubon_flag"]},
        "memorial_notice_opt_out": {"paths": ["deceased_profile.memorial_notice_opt_out"]},
        "deceased_note": {"paths": ["deceased_profile.deceased_note"]},
    },
    RecordEditLog.RecordType.SERVICE_SCHEDULE: {
        "household": {
            "paths": ["household_id"],
            "display_paths": ["household_name_snapshot", "household_id"],
        },
        "category": {"paths": ["category"]},
        "service_label": {"paths": ["service_label"]},
        "subject_name": {"paths": ["subject_name"]},
        "scheduled_date": {"paths": ["scheduled_date"]},
        "scheduled_time": {"paths": ["scheduled_time"]},
        "completed_on": {"paths": ["completed_on"]},
        "location": {"paths": ["location"]},
        "status": {"paths": ["status"]},
        "notes": {"paths": ["notes"]},
        "external_calendar_ref": {"paths": ["external_calendar_ref"]},
    },
    RecordEditLog.RecordType.OFFERING_PAYMENT: {
        "payer_name": {"paths": ["payer_name"]},
        "household": {
            "paths": ["household_id"],
            "display_paths": ["household_name_snapshot", "household_id"],
        },
        "received_on": {"paths": ["received_on"]},
        "payment_category": {"paths": ["payment_category"]},
        "amount": {"paths": ["amount"]},
        "payment_method": {"paths": ["payment_method"]},
        "received_by": {"paths": ["received_by"]},
        "notes": {"paths": ["notes"]},
    },
}


def _recent_record_history(record_type: str, record_id: int) -> list[dict]:
    rows = RecordEditLog.objects.filter(
        record_type=record_type,
        record_id=record_id,
    ).prefetch_related("field_changes").order_by("-created_at", "-id")[:8]
    history_entries = []
    for log in rows:
        history_entries.append(
            {
                "log": log,
                "field_changes": _history_field_changes(log),
                "before_json": json.dumps(log.before_data, ensure_ascii=False, indent=2),
                "after_json": json.dumps(log.after_data, ensure_ascii=False, indent=2),
            }
        )
    return history_entries


def _build_time_machine_field_options(
    *,
    record_type: str,
    record_id: int,
    form,
) -> dict[str, list[dict]]:
    field_specs = TIME_MACHINE_FIELD_SPECS.get(record_type, {})
    if not field_specs:
        return {}
    rows = list(
        RecordEditLog.objects.filter(record_type=record_type, record_id=record_id)
        .prefetch_related("field_changes")
        .order_by("-created_at", "-id")[:24]
    )
    if not rows:
        return {}
    options_by_field: dict[str, list[dict]] = {}
    for field_name, spec in field_specs.items():
        if field_name not in form.fields:
            continue
        current_value = _time_machine_normalize_field_value(field_name, form[field_name].value())
        seen = {current_value}
        field_options: list[dict] = []
        snapshots = []
        relevant_paths = set(spec.get("paths", [])) | set(spec.get("display_paths", []))
        for log in rows:
            change_rows = _record_field_change_rows(log)
            if change_rows:
                changed_paths = {row.field_path for row in change_rows}
                if not changed_paths.intersection(relevant_paths):
                    continue
            snapshots.append((log.before_data, log.created_at))
            snapshots.append((log.after_data, log.created_at))
        for snapshot, created_at in snapshots:
            raw_value = _time_machine_snapshot_value(snapshot, spec.get("paths", []))
            normalized_value = _time_machine_normalize_field_value(field_name, raw_value)
            if normalized_value in seen:
                continue
            display_value = _time_machine_display_value(
                field_name=field_name,
                raw_value=raw_value,
                snapshot=snapshot,
                display_paths=spec.get("display_paths", []),
                form=form,
            )
            seen.add(normalized_value)
            field_options.append(
                {
                    "value": normalized_value,
                    "label": display_value,
                    "applied_at": created_at.strftime("%Y-%m-%d %H:%M"),
                    "kind": _time_machine_field_kind(field_name, form),
                }
            )
        if field_options:
            options_by_field[field_name] = field_options
    return options_by_field


def _time_machine_snapshot_value(snapshot: dict, paths: list[str]) -> object:
    for path in paths:
        value = _snapshot_value(snapshot, path)
        if value not in (None, "", []):
            return value
    if paths:
        return _snapshot_value(snapshot, paths[0])
    return None


def _time_machine_field_kind(field_name: str, form) -> str:
    if field_name in {
        "memorial_notice_opt_out",
        "household_general_notice_opt_out",
        "household_memorial_notice_opt_out",
    }:
        return "checkbox"
    field = form.fields.get(field_name)
    if field is None:
        return "text"
    if getattr(field.widget, "input_type", "") == "checkbox":
        return "checkbox"
    if field.__class__.__name__.endswith("ChoiceField"):
        return "select"
    if getattr(field.widget, "input_type", "") == "textarea":
        return "textarea"
    if field.widget.__class__.__name__ == "Textarea":
        return "textarea"
    return "text"


def _time_machine_normalize_field_value(field_name: str, value) -> str:
    normalized = _normalize_snapshot_value(value)
    if field_name in {"head_gender", "gender"}:
        return str(normalized or "未決定")
    if field_name in {"birth_date_input", "death_date_input", "scheduled_date", "completed_on"}:
        return str(normalized or "")
    if field_name == "scheduled_time":
        text = str(normalized or "")
        return text[:5] if len(text) >= 5 else text
    if field_name in {"hatsubon_flag"}:
        if normalized is True:
            return "true"
        if normalized is False:
            return "false"
        return ""
    if field_name in {
        "memorial_notice_opt_out",
        "household_general_notice_opt_out",
        "household_memorial_notice_opt_out",
    }:
        return "true" if bool(normalized) else "false"
    if field_name in {"district_id", "age_at_death"}:
        return "" if normalized in (None, "") else str(normalized)
    return "" if normalized in (None,) else str(normalized)


def _time_machine_display_value(
    *,
    field_name: str,
    raw_value,
    snapshot: dict,
    display_paths: list[str],
    form,
) -> str:
    if field_name == "memorial_notice_opt_out":
        return "オン" if bool(raw_value) else "オフ"
    if field_name == "household_general_notice_opt_out":
        return "不要" if bool(raw_value) else "要"
    if field_name == "household_memorial_notice_opt_out":
        return "不要" if bool(raw_value) else "要"
    if field_name == "hatsubon_flag":
        if raw_value is True:
            return "はい"
        if raw_value is False:
            return "いいえ"
        return "未設定"
    if field_name in {"head_gender", "gender"}:
        return str(raw_value or "未決定")
    if field_name == "scheduled_time":
        text = str(raw_value or "")
        return text[:5] if len(text) >= 5 else (text or "空欄")
    if field_name == "district_id":
        label = _time_machine_snapshot_value(snapshot, display_paths)
        return str(label or "空欄")
    field = form.fields.get(field_name)
    normalized_value = _time_machine_normalize_field_value(field_name, raw_value)
    if field is not None and getattr(field, "choices", None):
        for choice_value, choice_label in field.choices:
            if str(choice_value) == normalized_value:
                return str(choice_label or "空欄")
    return "空欄" if normalized_value == "" else str(raw_value)
