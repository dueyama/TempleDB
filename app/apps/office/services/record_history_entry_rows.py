from __future__ import annotations

from apps.imports.models import District, RecordEditLog, RecordFieldChange, ServiceSchedule

from .record_history_snapshot import (
    _format_history_value,
    _history_log_event_scope,
    _infer_record_edit_action_kind,
    _normalize_snapshot_value,
    _snapshot_value,
)
from .record_history_urls import _record_history_edit_url


def _entries_module():
    from . import record_history_entries

    return record_history_entries


def _record_history_entry(
    log: RecordEditLog,
    source_id: str,
    latest_batch,
    current_url: str,
) -> dict:
    action = _record_log_action(log)
    current_record = _entries_module()._resolve_current_record_for_log(log, latest_batch)
    field_changes = _history_field_changes(log)
    edit_url = _record_history_edit_url(log, source_id, current_url, current_record is not None)
    return {
        "log": log,
        "action": action,
        "record_type_label": log.get_record_type_display(),
        "headline": _record_history_headline(log, action),
        "summary": _record_history_summary(action, field_changes),
        "field_changes": field_changes,
        "primary_field_changes": field_changes[:4],
        "extra_field_changes": field_changes[4:],
        "change_count": len(field_changes),
        "target_facts": _record_history_target_facts(log, current_record, len(field_changes)),
        "edit_url": edit_url,
        "current_state_label": _record_current_state_label(current_record),
        "current_record_exists": current_record is not None,
    }


def _record_log_action(log: RecordEditLog) -> dict:
    key = log.action_kind or _infer_record_edit_action_kind(log.before_data, log.after_data)
    if key == RecordEditLog.ActionKind.DELETE:
        return {"key": "delete", "label": "削除", "css_class": "delete"}
    if key == RecordEditLog.ActionKind.RESTORE:
        return {"key": "restore", "label": "復元", "css_class": "restore"}
    if key == RecordEditLog.ActionKind.RESET_SCHEDULE:
        return {"key": "reset_schedule", "label": "予定リセット", "css_class": "update"}
    if key == RecordEditLog.ActionKind.LINK_UPDATE:
        return {"key": "link_update", "label": "法要リンク調整", "css_class": "update"}
    return {"key": "update", "label": "更新", "css_class": "update"}


def _record_history_headline(log: RecordEditLog, action: dict) -> str:
    subject = _record_history_subject(log)
    if action["key"] == "delete":
        return f"{subject}を削除"
    if action["key"] == "restore":
        return f"{subject}を復元"
    if action["key"] == "reset_schedule":
        return f"{subject}の予定内容をリセット"
    if action["key"] == "link_update":
        return f"{subject}の法要リンクを調整"
    return f"{subject}を更新"


def _record_history_subject(log: RecordEditLog) -> str:
    entries = _entries_module()
    if log.record_type == RecordEditLog.RecordType.SERVICE_SCHEDULE:
        schedule_label = (
            _history_log_text_value(log, "service_label")
            or (log.record_label or "").strip()
            or "名称未設定"
        )
        person_name = _history_log_text_value(log, "subject_name") or _history_log_text_value(
            log,
            "person_name_snapshot",
        )
        household_name = _history_log_text_value(log, "household_name_snapshot")
        if _history_log_event_scope(log) == ServiceSchedule.EventScope.TEMPLE:
            counterpart = f"（{person_name}）" if person_name else ""
            return f"寺の予定「{schedule_label}」{counterpart}"
        if person_name and household_name and household_name != person_name:
            return f"{person_name}（{household_name}）の予定「{schedule_label}」"
        if person_name:
            return f"{person_name}の予定「{schedule_label}」"
        if household_name:
            return f"{household_name}の予定「{schedule_label}」"
    if log.record_type == RecordEditLog.RecordType.OFFERING_PAYMENT:
        category_label = (
            entries._payment_category_label(_history_log_text_value(log, "payment_category"))
            or "入金"
        )
        amount = _history_log_text_value(log, "amount")
        household_name = _history_log_text_value(log, "household_name_snapshot")
        temple_event = _history_log_event_scope(log) == ServiceSchedule.EventScope.TEMPLE
        person_name = (
            _history_log_text_value(log, "payer_name") or household_name or "匿名"
            if temple_event
            else _history_log_text_value(log, "person_name_snapshot") or "家全体"
        )
        service_label = _history_log_text_value(log, "service_label")
        amount_label = f"{amount}円" if amount else "金額未設定"
        base_label = f"{category_label} {amount_label}"
        if service_label:
            base_label = f"{base_label} / {service_label}"
        if household_name and person_name != "家全体" and household_name != person_name:
            return f"{person_name}（{household_name}）の入金「{base_label}」"
        if household_name and person_name == "家全体":
            return f"{household_name}の入金「{base_label}」"
        return f"{person_name}の入金「{base_label}」"
    record_type_label = log.get_record_type_display()
    record_label = (log.record_label or "").strip() or "名称未設定"
    return f"{record_type_label}「{record_label}」"


def _record_history_summary(action: dict, field_changes: list[dict]) -> str:
    action_key = action["key"]
    if action_key == "delete":
        base = "削除を記録しました。"
    elif action_key == "restore":
        base = "復元を記録しました。"
    elif action_key == "reset_schedule":
        base = "予定のリセットを記録しました。"
    elif action_key == "link_update":
        base = "法要リンクの調整を記録しました。"
    else:
        base = "更新内容を記録しました。"
    change_digest = _record_history_change_digest(field_changes)
    if change_digest:
        return f"{base} {change_digest}"
    return base


def _record_history_change_digest(field_changes: list[dict]) -> str:
    if not field_changes:
        return ""
    labels = [change["label"] for change in field_changes[:3]]
    if len(field_changes) > 3:
        return f"変更点: {'、'.join(labels)}、ほか{len(field_changes) - 3}項目"
    return f"変更点: {'、'.join(labels)}"


def _record_history_target_facts(log: RecordEditLog, current_record, change_count: int) -> list[dict]:
    entries = _entries_module()
    temple_event = _history_log_event_scope(log) == ServiceSchedule.EventScope.TEMPLE
    if log.record_type == RecordEditLog.RecordType.SERVICE_SCHEDULE:
        facts = [
            {
                "label": "予定名" if temple_event else "法要名",
                "value": _history_log_text_value(log, "service_label")
                or (log.record_label or "").strip()
                or "名称未設定",
            },
            {
                "label": "相手先" if temple_event else "対象者",
                "value": _history_log_text_value(log, "subject_name")
                or _history_log_text_value(log, "person_name_snapshot")
                or "未設定",
            },
            {
                "label": "現在の状態",
                "value": _record_current_state_label(current_record),
            },
        ]
        household_name = _history_log_text_value(log, "household_name_snapshot")
        if household_name:
            facts.append({"label": "家名", "value": household_name})
    elif log.record_type == RecordEditLog.RecordType.OFFERING_PAYMENT:
        donor_name = (
            _history_log_text_value(log, "payer_name")
            or _history_log_text_value(log, "household_name_snapshot")
            or "匿名"
        )
        category_label = (
            entries._payment_category_label(_history_log_text_value(log, "payment_category"))
            or "入金"
        )
        method_label = (
            entries._payment_method_label(_history_log_text_value(log, "payment_method"))
            or "未設定"
        )
        facts = [
            {"label": "区分", "value": category_label},
            {
                "label": "納入者" if temple_event else "対象者",
                "value": donor_name if temple_event else (
                    _history_log_text_value(log, "person_name_snapshot") or "家全体"
                ),
            },
            {
                "label": "予定区分" if temple_event else "法要区分",
                "value": "寺の予定" if temple_event else (
                    "法要紐づき" if _history_log_text_value(log, "legacy_schedule_id") else "法要外"
                ),
            },
            {
                "label": "金額",
                "value": f"{_history_log_text_value(log, 'amount') or '0'}円",
            },
            {
                "label": "受領方法",
                "value": method_label,
            },
            {
                "label": "現在の状態",
                "value": _record_current_state_label(current_record),
            },
        ]
        household_name = _history_log_text_value(log, "household_name_snapshot")
        if household_name:
            facts.append({"label": "家名", "value": household_name})
        service_label = _history_log_text_value(log, "service_label")
        if service_label:
            facts.append({"label": "予定名" if temple_event else "法要名", "value": service_label})
    else:
        facts = [
            {
                "label": "対象",
                "value": (log.record_label or "").strip() or "名称未設定",
            },
            {
                "label": "現在の状態",
                "value": _record_current_state_label(current_record),
            },
        ]
    if change_count:
        facts.append({"label": "変更項目", "value": f"{change_count}件"})
    if log.legacy_household_id:
        facts.append({"label": "台帳ID", "value": log.legacy_household_id})
    if log.legacy_person_id:
        facts.append({"label": "家族ID", "value": log.legacy_person_id})
    if log.legacy_schedule_id:
        facts.append({"label": "予定ID", "value": log.legacy_schedule_id})
    return facts


def _history_log_text_value(log: RecordEditLog, path: str) -> str:
    if _history_log_event_scope(log) == ServiceSchedule.EventScope.TEMPLE and log.after_data:
        # Temple-event snapshots are complete. An intentionally cleared donor or
        # household must not fall back to the old, now incorrect association.
        normalized = _normalize_snapshot_value(_snapshot_value(log.after_data, path))
        return "" if normalized in (None, "", []) else str(normalized).strip()
    for snapshot in (log.after_data, log.before_data):
        value = _snapshot_value(snapshot, path)
        normalized = _normalize_snapshot_value(value)
        if normalized in (None, "", []):
            continue
        return str(normalized).strip()
    return ""


def _record_field_change_rows(log: RecordEditLog) -> list[RecordFieldChange]:
    prefetched = getattr(log, "_prefetched_objects_cache", {})
    if "field_changes" in prefetched:
        return list(prefetched["field_changes"])
    return list(log.field_changes.all().order_by("sort_order", "id"))


def _history_field_changes(log: RecordEditLog) -> list[dict]:
    field_labels = _entries_module()._history_field_labels()
    if log.record_type == RecordEditLog.RecordType.DISTRICT:
        field_labels = {**field_labels, "name": "地区名"}
    rows = _record_field_change_rows(log)
    if rows:
        return [
            {
                "path": row.field_path,
                "label": field_labels.get(row.field_path, row.field_path),
                "before": _format_history_value(row.before_value),
                "after": _format_history_value(row.after_value),
            }
            for row in rows
        ]
    return [
        {
            "path": path,
            "label": field_labels.get(path, path),
            "before": _format_history_value(_snapshot_value(log.before_data, path)),
            "after": _format_history_value(_snapshot_value(log.after_data, path)),
        }
        for path in log.changed_fields
    ]


def _record_current_state_label(record) -> str:
    if record is None:
        return "現行台帳には未存在"
    if getattr(record, "is_deleted", False):
        return "削除済み"
    if isinstance(record, District) and not record.is_active:
        return "停止中"
    return "有効"
