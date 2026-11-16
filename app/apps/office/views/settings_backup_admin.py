from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from django.conf import settings as django_settings
from django.contrib import messages
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.forms import DatabaseBackupSettingForm
from apps.core.services import backup as backup_services
from apps.office import services
from apps.office.views.common import _ensure_superuser
from apps.office.web_support import (
    _backup_migration_guide_url,
    _backup_settings_url,
    _request_actor_label,
)

logger = logging.getLogger(__name__)

MIGRATION_BUNDLE_CONFIRMATION_FIELDS = (
    "include_private_migration_payload",
    "single_primary_cutover_confirmation",
    "restore_verification_confirmation",
)


def _sensitive_migration_response(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "no-store, private"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _migration_bundle_stream_sha256(bundle_file) -> tuple[str, int]:
    digest = hashlib.sha256()
    size_bytes = 0
    bundle_file.seek(0)
    try:
        while chunk := bundle_file.read(1024 * 1024):
            digest.update(chunk)
            size_bytes += len(chunk)
    finally:
        bundle_file.seek(0)
    return digest.hexdigest(), size_bytes


def backup_settings(request: HttpRequest) -> HttpResponse:
    active_source_id = services.operational_source_id()
    _ensure_superuser(request)
    backup_setting = backup_services.get_or_create_backup_setting()
    feature_enabled = backup_services.is_database_backup_supported()

    if request.method == "POST":
        form = DatabaseBackupSettingForm(request.POST, setting=backup_setting)
        if not feature_enabled:
            messages.error(request, "バックアップ設定は本運用DBでのみ変更できます。")
        elif form.is_valid():
            try:
                form.save_to_setting(backup_setting)
            except Exception as exc:
                form.add_error(None, str(exc))
            else:
                if (
                    backup_services.backup_destination_path_source(backup_setting)
                    == "env"
                ):
                    messages.success(
                        request,
                        "バックアップ設定を更新しました。保存先はこの機器の設定ファイルの値を使います。",
                    )
                else:
                    messages.success(request, "バックアップ保存先を更新しました。")
                return redirect(_backup_settings_url())
        if form.errors:
            messages.error(request, "バックアップ設定を保存できませんでした。入力内容を確認してください。")
    else:
        form = DatabaseBackupSettingForm(setting=backup_setting)

    recent_runs = backup_services.recent_backup_runs(limit=12)
    for run in recent_runs:
        run.artifact_exists = bool(run.backup_file_path and Path(run.backup_file_path).exists())
        run.manifest_exists = bool(run.manifest_file_path and Path(run.manifest_file_path).exists())
    latest_successful_run = backup_services.latest_successful_backup_run()
    latest_successful_run_artifact_exists = bool(
        latest_successful_run
        and latest_successful_run.backup_file_path
        and Path(latest_successful_run.backup_file_path).exists()
    )
    recent_verifications = backup_services.recent_verification_runs(limit=10)
    latest_scheduled_verification_success = (
        backup_services.latest_successful_scheduled_verification_run()
    )
    context = {
        "selected_source_id": active_source_id,
        "backup_form": form,
        "backup_setting": backup_setting,
        "backup_feature_enabled": feature_enabled,
        "backup_destination_status": (
            backup_services.backup_destination_status_for_setting(backup_setting)
        ),
        "backup_next_schedule_label": backup_services.next_scheduled_run_label(backup_setting),
        "backup_next_verification_schedule_label": (
            backup_services.next_scheduled_verification_label(backup_setting)
        ),
        "backup_migration_guide_url": _backup_migration_guide_url(),
        "latest_successful_backup_run": latest_successful_run,
        "latest_successful_backup_run_artifact_exists": latest_successful_run_artifact_exists,
        "recent_backup_runs": recent_runs,
        "recent_verification_runs": recent_verifications,
        "latest_scheduled_verification_success": latest_scheduled_verification_success,
        "database_engine": django_settings.DATABASES["default"]["ENGINE"],
        "database_engine_kind": backup_services.current_database_engine(),
    }
    return render(request, "office/backup_settings.html", context)


@require_POST
def run_backup_now(request: HttpRequest) -> HttpResponse:
    _ensure_superuser(request)
    if not backup_services.is_database_backup_supported():
        messages.error(request, "バックアップは本運用DBでのみ実行できます。")
        return redirect(_backup_settings_url())
    try:
        run = backup_services.perform_database_backup(
            trigger_kind="manual",
            requested_by_label=_request_actor_label(request),
        )
    except Exception as exc:
        messages.error(request, f"バックアップに失敗しました: {exc}")
    else:
        messages.success(request, f"バックアップを作成しました: {run.backup_file_name}")
    return redirect(_backup_settings_url())


@require_POST
def verify_backup_now(request: HttpRequest) -> HttpResponse:
    _ensure_superuser(request)
    if not backup_services.is_database_backup_supported():
        messages.error(request, "テスト復元は本運用DBでのみ実行できます。")
        return redirect(_backup_settings_url())
    backup_run = get_object_or_404(
        backup_services.backup_runs_for_current_engine(),
        pk=request.POST.get("run_id"),
    )
    try:
        verification = backup_services.perform_backup_verification(
            backup_run,
            requested_by_label=_request_actor_label(request),
            trigger_kind="manual",
        )
    except Exception as exc:
        messages.error(request, f"テスト復元に失敗しました: {exc}")
    else:
        messages.success(
            request,
            f"テスト復元を確認しました: {verification.verification_database_name}",
        )
    return redirect(_backup_settings_url())


def backup_migration_guide(request: HttpRequest) -> HttpResponse:
    _ensure_superuser(request)
    requested_run_id = (request.GET.get("run_id") or "").strip()
    backup_run = None
    if requested_run_id:
        backup_run = get_object_or_404(
            backup_services.backup_runs_for_current_engine(),
            pk=requested_run_id,
        )
    else:
        backup_run = backup_services.latest_successful_backup_run()
    guide = backup_services.build_backup_migration_guide_context(backup_run)
    context = {
        "guide": guide,
        "migration_bundle_entries": backup_services.build_backup_migration_bundle_entries(backup_run),
        "migration_bundle_filename": (
            backup_services.build_backup_migration_bundle_filename(backup_run)
            if backup_run is not None
            else ""
        ),
        "backup_settings_url": _backup_settings_url(),
    }
    return _sensitive_migration_response(
        render(request, "office/backup_migration_guide.html", context)
    )


@require_POST
def download_backup_migration_bundle(request: HttpRequest) -> HttpResponse:
    _ensure_superuser(request)
    backup_run = get_object_or_404(
        backup_services.backup_runs_for_current_engine(),
        pk=request.POST.get("run_id"),
    )
    confirmations_complete = all(
        request.POST.get(field_name) == "confirmed"
        for field_name in MIGRATION_BUNDLE_CONFIRMATION_FIELDS
    )
    if not confirmations_complete:
        logger.warning(
            "backup migration bundle rejected actor=%s run_id=%s reason=confirmation_missing",
            _request_actor_label(request),
            backup_run.id,
        )
        messages.error(
            request,
            "秘密情報の同梱、2台同時稼働の防止、新Macの復元確認の3点を確認してください。",
        )
        return _sensitive_migration_response(
            redirect(_backup_migration_guide_url(run_id=backup_run.id))
        )

    guide = backup_services.build_backup_migration_guide_context(backup_run)
    if not guide.get("can_create_bundle"):
        logger.warning(
            "backup migration bundle rejected actor=%s run_id=%s reason=readiness_blocked",
            _request_actor_label(request),
            backup_run.id,
        )
        messages.error(
            request,
            "同じバックアップの成功・manifest・別DBテスト復元が揃うまで、お引越しセットは作成できません。",
        )
        return _sensitive_migration_response(
            redirect(_backup_migration_guide_url(run_id=backup_run.id))
        )
    try:
        bundle_file, bundle_filename = backup_services.create_backup_migration_bundle(
            backup_run,
            include_private_migration_payload=True,
        )
    except Exception:
        logger.error(
            "backup migration bundle creation failed actor=%s run_id=%s reason=service_rejected",
            _request_actor_label(request),
            backup_run.id,
        )
        messages.error(
            request,
            "お引越しセットを作成できませんでした。"
            "バックアップ、manifest、別DBテスト復元と保存先を確認してください。",
        )
        return _sensitive_migration_response(
            redirect(_backup_migration_guide_url(run_id=backup_run.id))
        )
    try:
        bundle_sha256, bundle_size_bytes = _migration_bundle_stream_sha256(bundle_file)
    except Exception:
        logger.error(
            "backup migration bundle creation failed actor=%s run_id=%s reason=bundle_hash_failed",
            _request_actor_label(request),
            backup_run.id,
        )
        try:
            bundle_file.close()
        except Exception:
            pass
        messages.error(
            request,
            "お引越しセットを検証できませんでした。もう一度作成してください。",
        )
        return _sensitive_migration_response(
            redirect(_backup_migration_guide_url(run_id=backup_run.id))
        )
    logger.info(
        "backup migration bundle created actor=%s run_id=%s backup_sha256=%s "
        "bundle_sha256=%s bundle_size_bytes=%s "
        "payload=workspace,git,env,private,source_registry,durable_runtime,durable_generated",
        _request_actor_label(request),
        backup_run.id,
        backup_run.backup_sha256,
        bundle_sha256,
        bundle_size_bytes,
    )
    response = FileResponse(
        bundle_file,
        as_attachment=True,
        filename=bundle_filename,
        content_type="application/gzip",
    )
    response["X-TempleDB-Bundle-SHA256"] = bundle_sha256
    return _sensitive_migration_response(response)


__all__ = [
    "backup_settings",
    "backup_migration_guide",
    "run_backup_now",
    "verify_backup_now",
    "download_backup_migration_bundle",
]
