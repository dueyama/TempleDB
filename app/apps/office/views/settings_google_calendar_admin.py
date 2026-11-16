from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from apps.core.forms import GoogleCalendarSyncSettingForm
from apps.core.services import google_calendar as google_calendar_services
from apps.imports.models import GoogleCalendarSyncBinding
from apps.office import services
from apps.office.services import google_calendar_sync
from apps.office.views.common import _ensure_superuser
from apps.office.web_support import (
    _google_calendar_bulk_sync_status_url,
    _google_calendar_settings_url,
)


def google_calendar_settings(request: HttpRequest) -> HttpResponse:
    active_source_id = services.operational_source_id()
    _ensure_superuser(request)
    setting = google_calendar_services.get_or_create_google_calendar_sync_setting()

    if request.method == "POST":
        action = (request.POST.get("action") or "save_settings").strip()
        if action == "bulk_sync_google_calendar":
            configuration_errors = google_calendar_services.google_calendar_configuration_errors(setting)
            if not setting.enabled:
                messages.error(request, "Google カレンダー同期が無効です。先に有効化して保存してください。")
                return redirect(_google_calendar_bulk_sync_panel_url())
            if configuration_errors:
                messages.error(
                    request,
                    "Google カレンダー一括同期を実行できません。 " + " / ".join(configuration_errors),
                )
                return redirect(_google_calendar_bulk_sync_panel_url())
            try:
                status_payload = google_calendar_sync.start_google_calendar_bulk_sync_process(
                    requested_by_label=request.user.get_username().strip(),
                )
            except google_calendar_sync.GoogleCalendarBulkSyncAlreadyRunningError:
                messages.info(request, "Google カレンダー一括同期はすでに実行中です。下の進行状況を確認してください。")
                return redirect(_google_calendar_bulk_sync_panel_url())
            except Exception as exc:
                messages.error(request, f"Google カレンダー一括同期を開始できませんでした: {exc}")
                return redirect(_google_calendar_bulk_sync_panel_url())
            messages.success(
                request,
                f"Google カレンダー一括同期を開始しました。対象 {status_payload.get('total_count', 0)} 件です。",
            )
            return redirect(_google_calendar_bulk_sync_panel_url())
        form = GoogleCalendarSyncSettingForm(request.POST, instance=setting)
        if form.is_valid():
            form.save()
            messages.success(request, "Google カレンダー同期設定を保存しました。")
            return redirect(_google_calendar_settings_url())
        messages.error(request, "Google カレンダー同期設定を保存できませんでした。入力内容を確認してください。")
    else:
        form = GoogleCalendarSyncSettingForm(instance=setting)

    account_info = google_calendar_services.google_calendar_service_account_info()
    configuration_errors = google_calendar_services.google_calendar_configuration_errors(setting)
    sync_counts = {
        "pending": GoogleCalendarSyncBinding.objects.filter(
            sync_status=GoogleCalendarSyncBinding.SyncStatus.PENDING
        ).count(),
        "synced": GoogleCalendarSyncBinding.objects.filter(
            sync_status=GoogleCalendarSyncBinding.SyncStatus.SYNCED
        ).count(),
        "error": GoogleCalendarSyncBinding.objects.filter(
            sync_status=GoogleCalendarSyncBinding.SyncStatus.ERROR
        ).count(),
        "conflict": GoogleCalendarSyncBinding.objects.filter(
            sync_status=GoogleCalendarSyncBinding.SyncStatus.CONFLICT
        ).count(),
    }
    recent_bindings = list(
        GoogleCalendarSyncBinding.objects.select_related("primary_schedule")
        .order_by("-updated_at", "-id")[:20]
    )
    bulk_sync_status = google_calendar_sync.read_google_calendar_bulk_sync_status()
    context = {
        "selected_source_id": active_source_id,
        "google_calendar_form": form,
        "google_calendar_setting": setting,
        "google_calendar_account_info": account_info,
        "google_calendar_effective_base_url": google_calendar_services.google_calendar_base_url(setting),
        "google_calendar_effective_external_base_url": google_calendar_services.google_calendar_external_base_url(setting),
        "google_calendar_base_url_source": google_calendar_services.google_calendar_base_url_source(setting),
        "google_calendar_external_base_url_source": (
            google_calendar_services.google_calendar_external_base_url_source(setting)
        ),
        "google_calendar_configuration_errors": configuration_errors,
        "google_calendar_bulk_sync_ready": bool(setting.enabled) and not configuration_errors,
        "google_calendar_bulk_sync_running": bool(bulk_sync_status.get("running")),
        "google_calendar_bulk_sync_status": bulk_sync_status,
        "google_calendar_bulk_sync_status_url": _google_calendar_bulk_sync_status_url(),
        "google_calendar_sync_counts": sync_counts,
        "google_calendar_recent_bindings": recent_bindings,
    }
    return render(request, "office/google_calendar_settings.html", context)


@require_GET
def google_calendar_bulk_sync_status(request: HttpRequest) -> JsonResponse:
    _ensure_superuser(request)
    response = JsonResponse(google_calendar_sync.read_google_calendar_bulk_sync_status())
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


def _google_calendar_bulk_sync_panel_url() -> str:
    return f"{_google_calendar_settings_url()}#google-calendar-bulk-sync-panel"


__all__ = ["google_calendar_settings", "google_calendar_bulk_sync_status"]
