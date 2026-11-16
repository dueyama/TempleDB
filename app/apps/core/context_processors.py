from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings

from .services import tenant_policy, ui_appearance


def _realdata_preview_info():
    info = getattr(settings, "TEMPLEDB_PREVIEW_INFO", None)
    if not isinstance(info, dict):
        return None

    snapshot_label = "本番データの取得時刻は不明です。"
    try:
        snapshot_at = datetime.fromisoformat(info.get("snapshot_at", ""))
        if snapshot_at.tzinfo is not None:
            local_snapshot = snapshot_at.astimezone(ZoneInfo("Asia/Tokyo"))
            snapshot_label = local_snapshot.strftime("%Y年%m月%d日 %H:%M時点の本番データ")
    except (TypeError, ValueError, OverflowError):
        pass
    result = {"snapshot_label": snapshot_label}
    if settings.ROOT_URLCONF == "config.urls_realdata_preview":
        result["run_id"] = info.get("run_id", "")
    return result


def tenant_policy_labels(request):
    del request
    return {
        "deceased_labels": tenant_policy.deceased_field_labels(),
        "identifier_labels": tenant_policy.identifier_labels(),
        "print_heading_labels": tenant_policy.print_heading_labels(),
        "memorial_notice_table_labels": tenant_policy.memorial_notice_table_labels(),
        "role_labels": tenant_policy.role_labels(),
        "role_document_labels": tenant_policy.role_document_labels(),
        "tenant_terms": tenant_policy.terminology_terms(),
        "tenant_copy": tenant_policy.terminology_copy(),
        "ui_theme": ui_appearance.active_ui_theme(),
        "realdata_preview": _realdata_preview_info(),
    }
