from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.core.services import google_calendar as google_calendar_service
from apps.core.services import runtime_role
from apps.imports.models import GoogleCalendarSyncBinding, ServiceSchedule

from . import google_calendar_sync_payloads as sync_payloads
from . import google_calendar_sync_targets as sync_targets
from .google_calendar_sync_lock import (
    GoogleCalendarSyncLockTimeout,
    GoogleCalendarSyncLockUnsafe,
    google_calendar_sync_key_lock,
)
from .google_calendar_sync_types import GoogleCalendarSyncResult

logger = logging.getLogger(__name__)


def sync_google_calendar_for_schedule_ids(
    schedule_ids: list[int] | tuple[int, ...],
    *,
    explicit_sync_keys: list[str] | tuple[str, ...] = (),
    check_remote: bool = False,
    force_remote_update: bool = False,
) -> list[GoogleCalendarSyncResult]:
    sync_keys = set(sync_targets._normalized_sync_keys(explicit_sync_keys))
    schedule_pk_values = sync_targets._coerce_positive_ints(schedule_ids)
    if schedule_pk_values:
        schedules = ServiceSchedule.objects.filter(pk__in=schedule_pk_values)
        for schedule in schedules:
            sync_keys.add(sync_targets.google_calendar_sync_key_for_schedule(schedule))
    return sync_google_calendar_for_sync_keys(
        sorted(sync_keys),
        check_remote=check_remote,
        force_remote_update=force_remote_update,
    )


def sync_google_calendar_for_sync_keys(
    sync_keys: list[str] | tuple[str, ...],
    *,
    check_remote: bool = False,
    force_remote_update: bool = False,
) -> list[GoogleCalendarSyncResult]:
    """Sync committed data, updating deferred result lists after an outer commit."""
    resolved_sync_keys = sync_targets._normalized_sync_keys(sync_keys)
    if not resolved_sync_keys:
        return []
    if not runtime_role.google_calendar_access_allowed():
        message = runtime_role.google_calendar_block_message()
        return [
            GoogleCalendarSyncResult(
                sync_key,
                "disabled",
                message,
                "disabled",
            )
            for sync_key in resolved_sync_keys
        ]
    if not transaction.get_autocommit():
        # A file lock cannot protect a DB write that commits after its release.
        # Wait for the caller's real commit; rollback discards the callback.
        results = [GoogleCalendarSyncResult(
            key, "deferred", "保存完了後に Google カレンダーを同期します。", "pending",
        ) for key in resolved_sync_keys]

        def sync_after_commit() -> None:
            try:
                results[:] = sync_google_calendar_for_sync_keys(
                    resolved_sync_keys, check_remote=check_remote,
                    force_remote_update=force_remote_update,
                )
            except Exception as exc:
                # The business save has committed; never turn it into a 500.
                logger.error("Deferred Google Calendar sync failed (%s)", type(exc).__name__)
                results[:] = [GoogleCalendarSyncResult(
                    key, "error", "保存は完了しています。Google カレンダーを再同期してください。", "error",
                ) for key in resolved_sync_keys]

        transaction.on_commit(sync_after_commit)
        return results
    setting = google_calendar_service.get_or_create_google_calendar_sync_setting()
    results: list[GoogleCalendarSyncResult] = []
    for sync_key in resolved_sync_keys:
        try:
            result = _sync_google_calendar_for_key(
                sync_key,
                setting=setting,
                check_remote=check_remote,
                force_remote_update=force_remote_update,
            )
        except (
            google_calendar_service.GoogleCalendarApiError,
            google_calendar_service.GoogleCalendarConfigurationError,
        ) as exc:
            # Creation records ERROR before raising. Keep other keys recoverable
            # even when one member of a regrouped event cannot be synchronized.
            result = GoogleCalendarSyncResult(
                sync_key, "error", str(exc), GoogleCalendarSyncBinding.SyncStatus.ERROR
            )
        results.append(result)
    return results


def reconcile_google_calendar_sync(
    *,
    schedule_ids: list[int] | tuple[int, ...] = (),
    sync_keys: list[str] | tuple[str, ...] = (),
    check_remote: bool = True,
) -> list[GoogleCalendarSyncResult]:
    requested_keys = set(sync_targets._normalized_sync_keys(sync_keys))
    schedule_pk_values = sync_targets._coerce_positive_ints(schedule_ids)
    if schedule_pk_values:
        requested_keys.update(
            sync_targets.google_calendar_sync_key_for_schedule(schedule)
            for schedule in ServiceSchedule.objects.filter(pk__in=schedule_pk_values)
        )
    if not requested_keys:
        requested_keys.update(sync_targets._collect_google_calendar_reconcile_keys())
    return sync_google_calendar_for_sync_keys(sorted(requested_keys), check_remote=check_remote)


def _sync_google_calendar_for_key(
    sync_key: str,
    *,
    setting,
    check_remote: bool,
    force_remote_update: bool,
) -> GoogleCalendarSyncResult:
    if not transaction.get_autocommit():
        return sync_google_calendar_for_sync_keys(
            [sync_key], check_remote=check_remote, force_remote_update=force_remote_update,
        )[0]
    try:
        with google_calendar_sync_key_lock(sync_key):
            # No binding or target may be read before acquiring the key lock,
            # including for keys which do not have a binding yet.
            return _sync_google_calendar_for_locked_key(
                sync_key, setting=setting, check_remote=check_remote,
                force_remote_update=force_remote_update,
            )
    except GoogleCalendarSyncLockTimeout:
        # Do not overwrite the other worker's binding/error state.
        return GoogleCalendarSyncResult(
            sync_key, "error",
            "同じ予定の Google カレンダー同期が実行中です。少し待ってから再同期してください。",
            GoogleCalendarSyncBinding.SyncStatus.ERROR,
        )
    except (GoogleCalendarSyncLockUnsafe, OSError) as exc:
        logger.error("Google Calendar sync lock unavailable (%s)", type(exc).__name__)
        return GoogleCalendarSyncResult(
            sync_key, "error", "同期の排他制御を利用できません。実行環境を確認して再同期してください。",
            GoogleCalendarSyncBinding.SyncStatus.ERROR,
        )


def _sync_google_calendar_for_locked_key(
    sync_key: str,
    *,
    setting,
    check_remote: bool,
    force_remote_update: bool,
) -> GoogleCalendarSyncResult:
    binding = (
        GoogleCalendarSyncBinding.objects.select_related("primary_schedule")
        .filter(sync_key=sync_key)
        .first()
    )
    target = sync_targets._build_sync_target(sync_key)
    if not setting.enabled:
        return GoogleCalendarSyncResult(
            sync_key, "disabled", "Google カレンダー同期は無効です。", "disabled"
        )
    configuration_errors = google_calendar_service.google_calendar_configuration_errors(setting)
    if configuration_errors:
        message = " / ".join(configuration_errors)
        if target.primary_schedule is not None or binding is not None:
            _mark_binding_error(
                sync_key=sync_key,
                binding=binding,
                primary_schedule=target.primary_schedule,
                calendar_id=(setting.calendar_id or "").strip(),
                message=message,
            )
        return GoogleCalendarSyncResult(
            sync_key,
            "error",
            message,
            GoogleCalendarSyncBinding.SyncStatus.ERROR,
        )

    calendar_id = (setting.calendar_id or "").strip()
    if binding is not None and not target.should_exist:
        replacement_error = _check_replacement_before_deletion(binding, calendar_id=calendar_id)
        if replacement_error is not None:
            return replacement_error
    binding = _ensure_binding_calendar(binding, target.primary_schedule, sync_key, calendar_id)
    if not target.should_exist:
        return _delete_google_calendar_event_for_target(sync_key, target=target, binding=binding)

    assert target.payload is not None
    binding = _ensure_binding_record(
        binding,
        sync_key=sync_key,
        primary_schedule=target.primary_schedule,
        calendar_id=calendar_id,
    )
    if binding.google_event_id:
        if (
            target.fingerprint == binding.last_pushed_fingerprint
            and binding.sync_status == GoogleCalendarSyncBinding.SyncStatus.SYNCED
            and not binding.pending_event_deletions
            and not check_remote
        ):
            return GoogleCalendarSyncResult(
                sync_key,
                "unchanged",
                "Google カレンダーとの差分はありません。",
                GoogleCalendarSyncBinding.SyncStatus.SYNCED,
            )
        try:
            remote_event = google_calendar_service.fetch_google_calendar_event(
                calendar_id=calendar_id,
                event_id=binding.google_event_id,
            )
        except google_calendar_service.GoogleCalendarNotFoundError:
            remote_event = None
        except (
            google_calendar_service.GoogleCalendarApiError,
            google_calendar_service.GoogleCalendarConfigurationError,
        ) as exc:
            _mark_binding_error(
                sync_key=sync_key,
                binding=binding,
                primary_schedule=target.primary_schedule,
                calendar_id=calendar_id,
                message=str(exc),
            )
            return GoogleCalendarSyncResult(
                sync_key,
                "error",
                str(exc),
                GoogleCalendarSyncBinding.SyncStatus.ERROR,
            )

        if remote_event is None:
            created_event = _create_remote_google_calendar_event(
                calendar_id=calendar_id,
                payload=target.payload,
                target=target,
                binding=binding,
            )
            return _record_binding_success(
                binding=binding,
                primary_schedule=target.primary_schedule,
                calendar_id=calendar_id,
                event=created_event,
                fingerprint=target.fingerprint,
                action="created",
                message="Google カレンダーへ予定を再作成しました。",
            )

        remote_etag = str(remote_event.get("etag", "") or "").strip()
        if binding.google_etag and remote_etag and remote_etag != binding.google_etag:
            if not force_remote_update and (
                target.fingerprint != binding.last_pushed_fingerprint or check_remote
            ):
                _mark_binding_conflict(
                    binding=binding,
                    primary_schedule=target.primary_schedule,
                    calendar_id=calendar_id,
                    message="Google カレンダー側で変更を検出しました。TempleDB を確認してから再同期してください。",
                )
                return GoogleCalendarSyncResult(
                    sync_key,
                    "conflict",
                    "Google カレンダー側で変更を検出しました。TempleDB を確認してから再同期してください。",
                    GoogleCalendarSyncBinding.SyncStatus.CONFLICT,
                )
        if (
            target.fingerprint == binding.last_pushed_fingerprint
            and binding.sync_status == GoogleCalendarSyncBinding.SyncStatus.SYNCED
            and not binding.pending_event_deletions
            and not (force_remote_update and remote_etag and remote_etag != binding.google_etag)
        ):
            return GoogleCalendarSyncResult(
                sync_key,
                "unchanged",
                "Google カレンダーとの差分はありません。",
                GoogleCalendarSyncBinding.SyncStatus.SYNCED,
            )
        remote_temporal_mode = sync_payloads._google_calendar_event_temporal_mode(remote_event)
        target_temporal_mode = sync_payloads._google_calendar_event_temporal_mode(target.payload)
        if (
            remote_temporal_mode
            and target_temporal_mode
            and remote_temporal_mode != target_temporal_mode
        ):
            recreated_event = _recreate_remote_google_calendar_event(
                calendar_id=calendar_id,
                payload=target.payload,
                target=target,
                binding=binding,
            )
            return _record_binding_success(
                binding=binding,
                primary_schedule=target.primary_schedule,
                calendar_id=calendar_id,
                event=recreated_event,
                fingerprint=target.fingerprint,
                action="updated",
                message="Google カレンダーの予定を再作成しました。",
            )
        try:
            updated_event = google_calendar_service.update_google_calendar_event(
                calendar_id=calendar_id,
                event_id=binding.google_event_id,
                body=target.payload,
            )
        except (
            google_calendar_service.GoogleCalendarApiError,
            google_calendar_service.GoogleCalendarConfigurationError,
        ) as exc:
            _mark_binding_error(
                sync_key=sync_key,
                binding=binding,
                primary_schedule=target.primary_schedule,
                calendar_id=calendar_id,
                message=str(exc),
            )
            return GoogleCalendarSyncResult(
                sync_key,
                "error",
                str(exc),
                GoogleCalendarSyncBinding.SyncStatus.ERROR,
            )
        return _record_binding_success(
            binding=binding,
            primary_schedule=target.primary_schedule,
            calendar_id=calendar_id,
            event=updated_event,
            fingerprint=target.fingerprint,
            action="updated",
            message="Google カレンダーの予定を更新しました。",
        )

    created_event = _create_remote_google_calendar_event(
        calendar_id=calendar_id,
        payload=target.payload,
        target=target,
        binding=binding,
    )
    return _record_binding_success(
        binding=binding,
        primary_schedule=target.primary_schedule,
        calendar_id=calendar_id,
        event=created_event,
        fingerprint=target.fingerprint,
        action="created",
        message="Google カレンダーへ予定を作成しました。",
    )


def _create_remote_google_calendar_event(*, calendar_id: str, payload: dict, target, binding) -> dict:
    try:
        return google_calendar_service.create_google_calendar_event(
            calendar_id=calendar_id,
            body=payload,
        )
    except (
        google_calendar_service.GoogleCalendarApiError,
        google_calendar_service.GoogleCalendarConfigurationError,
    ) as exc:
        _mark_binding_error(
            sync_key=target.sync_key,
            binding=binding,
            primary_schedule=target.primary_schedule,
            calendar_id=calendar_id,
            message=str(exc),
        )
        raise


def _recreate_remote_google_calendar_event(
    *,
    calendar_id: str,
    payload: dict,
    target,
    binding: GoogleCalendarSyncBinding,
) -> dict:
    previous_event_id = (binding.google_event_id or "").strip()
    created_event = _create_remote_google_calendar_event(
        calendar_id=calendar_id,
        payload=payload,
        target=target,
        binding=binding,
    )
    created_event_id = str(created_event.get("id", "") or "").strip()
    if previous_event_id and previous_event_id != created_event_id:
        _queue_event_deletion(binding, calendar_id=calendar_id, event_id=previous_event_id)
    # _record_binding_success persists the replacement ID and cleanup queue
    # together before issuing DELETE. A failed create never queues the live ID.
    return created_event


def _queue_event_deletion(
    binding: GoogleCalendarSyncBinding, *, calendar_id: str, event_id: str
) -> None:
    reference = {"calendar_id": calendar_id, "event_id": event_id}
    pending = list(binding.pending_event_deletions)
    if reference not in pending:
        pending.append(reference)
    binding.pending_event_deletions = pending


def _delete_pending_google_calendar_events(
    binding: GoogleCalendarSyncBinding,
) -> GoogleCalendarSyncResult | None:
    for reference in list(binding.pending_event_deletions):
        message = ""
        if (
            reference["calendar_id"] == binding.calendar_id
            and reference["event_id"] == binding.google_event_id
        ):
            message = "削除待ちの予定が現在の同期予定と一致するため、削除を保留しました。"
        else:
            try:
                google_calendar_service.delete_google_calendar_event(
                    calendar_id=reference["calendar_id"], event_id=reference["event_id"]
                )
            except google_calendar_service.GoogleCalendarNotFoundError:
                pass
            except (
                google_calendar_service.GoogleCalendarApiError,
                google_calendar_service.GoogleCalendarConfigurationError,
            ):
                message = "置き換え前の Google カレンダー予定を削除できませんでした。再同期で削除を再試行します。"
        if message:
            _mark_binding_error(
                sync_key=binding.sync_key,
                binding=binding,
                primary_schedule=binding.primary_schedule,
                calendar_id=binding.calendar_id,
                message=message,
            )
            return GoogleCalendarSyncResult(
                binding.sync_key, "error", message, GoogleCalendarSyncBinding.SyncStatus.ERROR
            )
        binding.pending_event_deletions.remove(reference)
        binding.save(update_fields=["pending_event_deletions", "updated_at"])
    return None


def _check_replacement_before_deletion(
    binding: GoogleCalendarSyncBinding, *, calendar_id: str
) -> GoogleCalendarSyncResult | None:
    schedule = binding.primary_schedule
    # Older failed syncs may have cleared the FK of an obsolete standalone key.
    if schedule is None:
        kind, value = sync_targets._split_sync_key(binding.sync_key)
        if kind == "schedule" and value.isdigit():
            schedule = ServiceSchedule.objects.filter(pk=int(value)).first()
    if schedule is None or schedule.deleted_at is not None:
        return None
    replacement_key = sync_targets.google_calendar_sync_key_for_schedule(schedule)
    if replacement_key == binding.sync_key:
        return None
    replacement_target = sync_targets._build_sync_target(replacement_key)
    if not replacement_target.should_exist:
        return None
    replacement = GoogleCalendarSyncBinding.objects.filter(sync_key=replacement_key).first()
    if (
        replacement is not None
        and replacement.google_event_id
        and replacement.calendar_id == calendar_id
        and replacement.sync_status == GoogleCalendarSyncBinding.SyncStatus.SYNCED
        and replacement.last_pushed_fingerprint == replacement_target.fingerprint
        and not replacement.pending_event_deletions
    ):
        return None
    message = "まとめ先の Google カレンダー予定の同期が完了していないため、元の予定を保持しています。再同期してください。"
    _mark_binding_error(
        sync_key=binding.sync_key, binding=binding, primary_schedule=schedule,
        calendar_id=binding.calendar_id, message=message,
    )
    return GoogleCalendarSyncResult(
        binding.sync_key, "error", message, GoogleCalendarSyncBinding.SyncStatus.ERROR
    )


def _delete_google_calendar_event_for_target(
    sync_key: str,
    *,
    target,
    binding: GoogleCalendarSyncBinding | None,
) -> GoogleCalendarSyncResult:
    if binding is None:
        return GoogleCalendarSyncResult(
            sync_key,
            "skipped",
            "同期対象のイベントはありません。",
            "missing",
        )
    message = (
        "Google カレンダー上のイベントを削除しました。"
        if binding.google_event_id or binding.pending_event_deletions
        else "同期メタデータを整理しました。"
    )
    deletion_error = _delete_pending_google_calendar_events(binding)
    if binding.google_event_id:
        try:
            google_calendar_service.delete_google_calendar_event(
                calendar_id=binding.calendar_id,
                event_id=binding.google_event_id,
            )
        except google_calendar_service.GoogleCalendarNotFoundError:
            message = "Google カレンダー上にイベントが無かったため同期メタデータを整理しました。"
        except (
            google_calendar_service.GoogleCalendarApiError,
            google_calendar_service.GoogleCalendarConfigurationError,
        ) as exc:
            message = str(exc)
            if deletion_error is not None:
                message += f" / {deletion_error.message}"
            _mark_binding_error(
                sync_key=sync_key, binding=binding,
                primary_schedule=target.primary_schedule,
                calendar_id=binding.calendar_id, message=message,
            )
            return GoogleCalendarSyncResult(
                sync_key, "error", message, GoogleCalendarSyncBinding.SyncStatus.ERROR,
            )
        binding.google_event_id = ""
        binding.google_etag = ""
        binding.last_pushed_fingerprint = ""
        binding.save(update_fields=[
            "google_event_id", "google_etag", "last_pushed_fingerprint", "updated_at",
        ])
    if deletion_error is not None:
        return deletion_error
    binding.delete()
    return GoogleCalendarSyncResult(
        sync_key,
        "deleted",
        message,
        "missing",
    )


def _record_binding_success(
    *,
    binding: GoogleCalendarSyncBinding,
    primary_schedule: ServiceSchedule | None,
    calendar_id: str,
    event: dict,
    fingerprint: str,
    action: str,
    message: str,
) -> GoogleCalendarSyncResult:
    binding.primary_schedule = primary_schedule
    binding.calendar_id = calendar_id
    binding.google_event_id = str(event.get("id", "") or "").strip()
    binding.google_etag = str(event.get("etag", "") or "").strip()
    binding.last_pushed_fingerprint = fingerprint
    binding.sync_status = (
        GoogleCalendarSyncBinding.SyncStatus.PENDING
        if binding.pending_event_deletions
        else GoogleCalendarSyncBinding.SyncStatus.SYNCED
    )
    binding.last_synced_at = timezone.now()
    binding.last_error_message = ""
    binding.save(
        update_fields=[
            "primary_schedule",
            "calendar_id",
            "google_event_id",
            "google_etag",
            "pending_event_deletions",
            "last_pushed_fingerprint",
            "sync_status",
            "last_synced_at",
            "last_error_message",
            "updated_at",
        ]
    )
    deletion_error = _delete_pending_google_calendar_events(binding)
    if deletion_error is not None:
        return deletion_error
    if binding.sync_status != GoogleCalendarSyncBinding.SyncStatus.SYNCED:
        binding.sync_status = GoogleCalendarSyncBinding.SyncStatus.SYNCED
        binding.save(update_fields=["sync_status", "updated_at"])
    return GoogleCalendarSyncResult(
        binding.sync_key,
        action,
        message,
        GoogleCalendarSyncBinding.SyncStatus.SYNCED,
    )


def _mark_binding_error(
    *,
    sync_key: str,
    binding: GoogleCalendarSyncBinding | None,
    primary_schedule: ServiceSchedule | None,
    calendar_id: str,
    message: str,
) -> None:
    resolved_binding = _ensure_binding_record(
        binding,
        sync_key=sync_key,
        primary_schedule=primary_schedule,
        calendar_id=calendar_id,
    )
    if primary_schedule is not None:
        resolved_binding.primary_schedule = primary_schedule
    if not resolved_binding.google_event_id:
        resolved_binding.calendar_id = calendar_id
    resolved_binding.sync_status = GoogleCalendarSyncBinding.SyncStatus.ERROR
    resolved_binding.last_error_message = (message or "").strip()
    resolved_binding.save(
        update_fields=[
            "primary_schedule",
            "calendar_id",
            "sync_status",
            "last_error_message",
            "updated_at",
        ]
    )


def _mark_binding_conflict(
    *,
    binding: GoogleCalendarSyncBinding,
    primary_schedule: ServiceSchedule | None,
    calendar_id: str,
    message: str,
) -> None:
    if primary_schedule is not None:
        binding.primary_schedule = primary_schedule
    binding.calendar_id = calendar_id
    binding.sync_status = GoogleCalendarSyncBinding.SyncStatus.CONFLICT
    binding.last_error_message = (message or "").strip()
    binding.save(
        update_fields=[
            "primary_schedule",
            "calendar_id",
            "sync_status",
            "last_error_message",
            "updated_at",
        ]
    )


def _ensure_binding_record(
    binding: GoogleCalendarSyncBinding | None,
    *,
    sync_key: str,
    primary_schedule: ServiceSchedule | None,
    calendar_id: str,
) -> GoogleCalendarSyncBinding:
    if binding is not None:
        return binding
    return GoogleCalendarSyncBinding.objects.create(
        sync_key=sync_key,
        primary_schedule=primary_schedule,
        calendar_id=calendar_id,
        sync_status=GoogleCalendarSyncBinding.SyncStatus.PENDING,
    )


def _ensure_binding_calendar(
    binding: GoogleCalendarSyncBinding | None,
    primary_schedule: ServiceSchedule | None,
    sync_key: str,
    calendar_id: str,
) -> GoogleCalendarSyncBinding | None:
    if binding is None:
        return None
    if (binding.calendar_id or "").strip() == calendar_id:
        return binding
    if binding.google_event_id and binding.calendar_id:
        _queue_event_deletion(
            binding, calendar_id=binding.calendar_id, event_id=binding.google_event_id
        )
    if primary_schedule is not None:
        binding.primary_schedule = primary_schedule
    binding.calendar_id = calendar_id
    binding.google_event_id = ""
    binding.google_etag = ""
    binding.last_pushed_fingerprint = ""
    binding.sync_status = GoogleCalendarSyncBinding.SyncStatus.PENDING
    binding.last_error_message = ""
    binding.save(
        update_fields=[
            "primary_schedule",
            "calendar_id",
            "google_event_id",
            "google_etag",
            "pending_event_deletions",
            "last_pushed_fingerprint",
            "sync_status",
            "last_error_message",
            "updated_at",
        ]
    )
    return binding
