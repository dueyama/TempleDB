"""Ordinary temple events and their receipts, without synthetic households."""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum

from apps.imports.models import Household, OfferingPayment, RecordEditLog, ServiceSchedule

from . import google_calendar_sync
from .canonical_ledger import resolve_canonical_ledger_context
from .offering_payments import create_offering_payment_logs_for_diff
from .record_history_mutations import _create_record_edit_log
from .record_history_snapshot import (
    _serialize_offering_payment_record,
    _serialize_service_schedule_record,
)

logger = logging.getLogger(__name__)

EVENT_FIELDS = (
    "service_label",
    "scheduled_date",
    "scheduled_time",
    "location",
    "subject_name",
    "household",
    "status",
    "completed_on",
    "notes",
)
PAYMENT_FIELDS = (
    "payer_name",
    "household",
    "received_on",
    "amount",
    "payment_category",
    "payment_method",
    "received_by",
    "notes",
)


@dataclass
class TempleEventSaveResult:
    event: ServiceSchedule
    sync_results: list = field(default_factory=list)


def temple_event_households(context):
    return (
        Household.objects.filter(batch=context.provenance_batch, deleted_at__isnull=True)
        .select_related("head_person")
        .order_by("household_uid")
    )


def temple_event_list(*, year, query=""):
    events = ServiceSchedule.objects.filter(
        event_scope=ServiceSchedule.EventScope.TEMPLE,
        deleted_at__isnull=True,
        scheduled_date__year=year,
    )
    if query:
        events = events.filter(
            Q(service_label__icontains=query)
            | Q(subject_name__icontains=query)
            | Q(notes__icontains=query)
            | Q(household_name_snapshot__icontains=query)
        )
    return (
        events.select_related("household")
        .annotate(
            payment_total=Sum("offering_payments__amount", default=Decimal("0")),
            payment_count=Count("offering_payments"),
        )
        .order_by("scheduled_date", "scheduled_time", "pk")
    )


def _clear_person_and_household_snapshots(record):
    record.person = None
    record.person_uid = ""
    record.person_name_snapshot = ""
    if record.household is None:
        record.household_uid = ""
        record.household_name_snapshot = ""


def _validate_household(household, context):
    if (
        household is not None
        and not temple_event_households(context).filter(pk=household.pk).exists()
    ):
        raise ValidationError("現在の帳簿にある家だけを指定できます。")


@transaction.atomic
def save_temple_event(
    *,
    event_id=None,
    values,
    payments,
    deleted_payment_ids=(),
    expected_version="",
    editor_label,
    change_note="",
):
    """Save event + receipt changes + audit atomically; sync only after commit.

    `payments` is a sequence of field dictionaries, with optional integer `id`.
    Existing receipt IDs must belong to this event. Scope is never caller-editable.
    """
    context = resolve_canonical_ledger_context()
    if not editor_label.strip():
        raise ValidationError("変更者を指定してください。")
    if event_id is not None:
        event = ServiceSchedule.objects.select_for_update().get(
            pk=event_id, event_scope=ServiceSchedule.EventScope.TEMPLE, deleted_at__isnull=True
        )
        if not expected_version or expected_version != event.updated_at.isoformat():
            raise ValidationError(
                "別の画面で更新されています。再読み込みしてから変更してください。"
            )
        before = _serialize_service_schedule_record(event)
    else:
        event = ServiceSchedule(
            event_scope=ServiceSchedule.EventScope.TEMPLE,
            category=ServiceSchedule.Category.OTHER,
            record_origin=ServiceSchedule.Origin.MANUAL,
            schedule_uid=f"temple-{uuid4().hex}",
            source_table="manual_service_schedule",
            is_demo_data=settings.TEMPLEDB_DEMO_MODE,
        )
        before = {}
    for key in EVENT_FIELDS:
        if key in values:
            setattr(event, key, values[key])
    _validate_household(event.household, context)
    event.related_batch = context.provenance_batch
    event.legacy_source_id = context.source_id
    event.source_export_batch = context.provenance_batch.prepared_snapshot_id
    event.legacy_pk_text = event.schedule_uid
    event.category = ServiceSchedule.Category.OTHER
    event.link_group_key = ""
    _clear_person_and_household_snapshots(event)
    if not event.scheduled_date:
        raise ValidationError("日付を入力してください。")
    if event.status == ServiceSchedule.Status.COMPLETED:
        event.completed_on = event.completed_on or event.scheduled_date
    else:
        event.completed_on = None
    event.full_clean()
    event.save()

    existing = {
        p.pk: p
        for p in OfferingPayment.objects.select_for_update(of=("self",))
        .filter(service_schedule=event)
        .select_related("household", "person", "service_schedule")
    }
    snapshots = {pk: _serialize_offering_payment_record(p) for pk, p in existing.items()}
    delete_ids = set(deleted_payment_ids)
    row_ids = [row["id"] for row in payments if row.get("id") is not None]
    if (
        not delete_ids.issubset(existing)
        or not set(row_ids).issubset(existing)
        or len(row_ids) != len(set(row_ids))
        or delete_ids.intersection(row_ids)
    ):
        raise ValidationError("入金の対象が一致しません。再読み込みしてください。")
    for row in payments:
        payment = (
            existing[row["id"]]
            if row.get("id") is not None
            else OfferingPayment(service_schedule=event)
        )
        for key in PAYMENT_FIELDS:
            if key in row:
                setattr(payment, key, row[key])
        _validate_household(payment.household, context)
        payment.payment_method = payment.payment_method or OfferingPayment.Method.CASH
        payment.related_batch = context.provenance_batch
        payment.legacy_source_id = context.source_id
        payment.is_demo_data = event.is_demo_data
        _clear_person_and_household_snapshots(payment)
        payment.full_clean()
        if payment.amount < 0:
            raise ValidationError("金額は0円以上で入力してください。")
        payment.save()
    if delete_ids:
        OfferingPayment.objects.filter(service_schedule=event, pk__in=delete_ids).delete()
    create_offering_payment_logs_for_diff(
        before_snapshots=snapshots,
        before_records=existing,
        after_payments=list(
            OfferingPayment.objects.filter(service_schedule=event).select_related(
                "household", "person", "service_schedule"
            )
        ),
        editor_label=editor_label,
        change_note=change_note,
    )
    _create_record_edit_log(
        record_type=RecordEditLog.RecordType.SERVICE_SCHEDULE,
        record=event,
        before_data=before,
        after_data=_serialize_service_schedule_record(event),
        editor_label=editor_label,
        change_note=change_note,
    )
    result = TempleEventSaveResult(event)
    sync_key = google_calendar_sync.google_calendar_sync_key_for_schedule(event)

    def sync_after_commit():
        try:
            result.sync_results.extend(
                google_calendar_sync.sync_google_calendar_for_sync_keys([sync_key])
            )
        except Exception:
            # The business transaction is already committed: never invite a duplicate save.
            logger.exception("Temple event calendar sync failed for schedule %s", event.pk)
            result.sync_results.append(
                google_calendar_sync.GoogleCalendarSyncResult(
                    sync_key=sync_key,
                    action="error",
                    message="予定と入金は保存済みですが、カレンダー同期に失敗しました。同期設定で状態を確認してください。",
                    binding_status="error",
                )
            )

    transaction.on_commit(sync_after_commit)
    return result
