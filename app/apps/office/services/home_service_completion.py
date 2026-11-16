"""Home-card completion using the canonical schedule/payment/history save path."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.imports.models import OfferingPayment, ServiceSchedule

from .google_calendar_sync_targets import google_calendar_sync_key_for_schedule
from .offering_payments import snapshot_service_schedule_payments
from .record_history_snapshot import _serialize_service_schedule_record
from .service_schedule_save import (
    ServiceScheduleSaveOptions,
    ServiceScheduleSaveSnapshot,
    save_service_schedule,
)

SALT = "office.home-service-completion.v1"
STALE_MESSAGE = "予定や入金が変更されています。ホームを再読み込みして内容を確認してください。"


def _eligible(records: list[ServiceSchedule]) -> bool:
    return bool(records) and all(
        row.event_scope == ServiceSchedule.EventScope.HOUSEHOLD
        and row.household_id and row.related_batch_id and row.deleted_at is None
        and row.status == ServiceSchedule.Status.SCHEDULED and row.scheduled_date
        and (row.household_id, row.scheduled_date, row.scheduled_time, row.location)
        == (records[0].household_id, records[0].scheduled_date, records[0].scheduled_time, records[0].location)
        for row in records
    )


def _state(records: list[ServiceSchedule], payments: list[OfferingPayment]) -> dict:
    return {
        "schedules": [[row.pk, row.updated_at.isoformat()] for row in records],
        "payments": [[row.pk, row.updated_at.isoformat()] for row in payments],
    }


def attach_home_completion_entries(summary: dict) -> None:
    """Batch-load only the displayed cards and their groups; do not add ledger UI."""
    entries = [entry for key in ("today_events", "next_events", "overdue_events")
               for entry in summary.get(key, []) if entry.get("schedule_pk") and not entry.get("is_temple_event")]
    ids = {member["schedule_pk"] for entry in entries
           for member in [entry, *entry.get("linked_entries", [])]}
    groups = {entry["link_group_key"] for entry in entries if entry.get("link_group_key")}
    if not ids:
        return
    records = list(ServiceSchedule.objects.filter(
        Q(pk__in=ids) | Q(link_group_key__in=groups), deleted_at__isnull=True,
    ).order_by("pk"))
    by_id = {row.pk: row for row in records}
    by_group = defaultdict(list)
    for row in records:
        if row.link_group_key:
            by_group[row.link_group_key].append(row)
    payments_by_schedule = defaultdict(list)
    for payment in OfferingPayment.objects.filter(service_schedule__in=records).order_by("pk"):
        payments_by_schedule[payment.service_schedule_id].append(payment)
    for entry in entries:
        master = by_id.get(entry["schedule_pk"])
        if master is None:
            continue
        members = by_group[master.link_group_key] if master.link_group_key else [master]
        displayed_ids = {row["schedule_pk"] for row in [entry, *entry.get("linked_entries", [])]}
        if {row.pk for row in members} != displayed_ids or not _eligible(members):
            continue
        payments = sorted([payment for row in members for payment in payments_by_schedule[row.pk]], key=lambda p: p.pk)
        entry["quick_completion"] = {
            "schedule_id": master.pk,
            "state": signing.dumps({"master": master.pk, **_state(members, payments)}, salt=SALT, compress=True),
            "completed_on": min(master.scheduled_date, timezone.localdate()),
            "has_payments": bool(payments),
            "payment_total": sum((payment.amount for payment in payments), Decimal(0)),
            "member_count": len(members),
        }


@transaction.atomic
def complete_home_service(
    *, schedule_id: int, state: str, amount: Decimal | None, completed_on: date,
    payment_method: str, editor_label: str, source_id: str,
) -> list[str]:
    """Preserve links/dates, complete the displayed group and record one receipt.

    Signed versions reject stale tabs and repeated submissions, including a new
    payment added from another page. Row locks serialize home submissions.
    """
    try:
        expected = signing.loads(state, salt=SALT, max_age=86400)
    except signing.BadSignature as exc:
        raise ValidationError("画面の有効期限が切れました。ホームを再読み込みしてください。") from exc
    master = ServiceSchedule.objects.filter(pk=schedule_id, legacy_source_id=source_id).first()
    if master is None or expected.get("master") != schedule_id:
        raise ValidationError(STALE_MESSAGE)
    query = Q(pk=master.pk)
    if master.link_group_key:
        query |= Q(link_group_key=master.link_group_key)
    members = list(ServiceSchedule.objects.select_for_update(of=("self",)).filter(
        query, deleted_at__isnull=True,
    ).select_related("household", "person", "person__deceased_profile", "related_batch__source").order_by("pk"))
    payments = list(OfferingPayment.objects.select_for_update().filter(service_schedule__in=members).order_by("pk"))
    if (not _eligible(members) or any(row.legacy_source_id != source_id for row in members)
            or _state(members, payments) != {key: expected.get(key) for key in ("schedules", "payments")}):
        raise ValidationError(STALE_MESSAGE)
    if amount is not None and payments:
        raise ValidationError("入金は登録済みです。金額は空欄で完了するか、法要の編集画面で確認してください。")
    if completed_on > timezone.localdate() or payment_method not in OfferingPayment.Method.values:
        raise ValidationError("実施・入金日または受領方法を確認してください。")
    if amount is not None and (not amount.is_finite() or amount < 0):
        raise ValidationError("お布施金額を確認してください。")
    sync_keys = []
    for row in members:
        # Funeral/first-seventh propagation may already have completed this row.
        row.refresh_from_db()
        if row.status == ServiceSchedule.Status.COMPLETED:
            continue
        before_payments, payment_records = snapshot_service_schedule_payments(row)
        snapshot = ServiceScheduleSaveSnapshot(
            before_data=_serialize_service_schedule_record(row), payment_snapshots=before_payments,
            payment_records=payment_records, link_group_key=row.link_group_key,
            sync_key=google_calendar_sync_key_for_schedule(row),
        )
        row.status, row.completed_on = ServiceSchedule.Status.COMPLETED, completed_on

        def persist_payment(row=row):
            if row.pk == schedule_id and amount is not None:
                payment = OfferingPayment(
                    service_schedule=row, household=row.household, person=row.person,
                    related_batch=row.related_batch, received_on=completed_on, amount=amount,
                    payment_category=OfferingPayment.Category.OFFERING, payment_method=payment_method,
                    is_demo_data=row.is_demo_data,
                )
                payment.full_clean()
                payment.save()

        result = save_service_schedule(
            row, batch=row.related_batch, person=row.person, source_id=source_id,
            # Preserve group membership. Each member receives only completion fields.
            options=ServiceScheduleSaveOptions(supports_linking=False), snapshot=snapshot,
            persist_payments=persist_payment, editor_label=editor_label,
            change_note="寺務ホームからお布施入力・完了保存",
        )
        sync_keys.extend(result.sync_keys)
    return sorted(set(sync_keys))
