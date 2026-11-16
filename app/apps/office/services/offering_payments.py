from __future__ import annotations

from decimal import Decimal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.urls import reverse

from apps.imports import canonical_population
from apps.imports.models import Household, ImportBatch, OfferingPayment, ServiceSchedule

HOUSEHOLD_PAYMENT_PERSON_FILTER_VALUE = "__household__"


def attach_household_browser_payment_context(
    context: dict,
    *,
    batch: ImportBatch | None,
    current_url: str,
    payment_category_filter: str = "",
    payment_person_filter: str = "",
) -> None:
    detail = context.get("detail")
    if not detail or context.get("data_backend") != "db":
        return
    household_id = str(detail.get("summary", {}).get("household_id") or "").strip()
    if not household_id:
        return
    summary, entries = build_household_payment_entries(
        batch=batch,
        household_id=household_id,
        current_url=current_url,
        payment_category_filter=payment_category_filter,
        payment_person_filter=payment_person_filter,
    )
    detail["payment_summary"] = summary
    detail["payment_entries"] = entries
    detail["new_payment_url"] = household_offering_payment_create_url(
        household_id=household_id,
        current_url=current_url,
    )
    detail["current_members"] = [
        _attach_member_payment_url(
            member,
            household_id=household_id,
            current_url=current_url,
        )
        for member in detail.get("current_members", [])
    ]
    detail["memorial_members"] = [
        _attach_member_payment_url(
            member,
            household_id=household_id,
            current_url=current_url,
        )
        for member in detail.get("memorial_members", [])
    ]


def build_household_payment_entries(
    *,
    batch: ImportBatch | None,
    household_id: str,
    current_url: str,
    payment_category_filter: str = "",
    payment_person_filter: str = "",
) -> tuple[dict[str, object], list[dict]]:
    source_id = (
        batch.source.source_id
        if batch is not None
        else Household.objects.filter(
            household_uid=household_id,
            deleted_at__isnull=True,
        )
        .values_list("legacy_source_id", flat=True)
        .first()
    )
    canonical_population.canonical_provenance_import_batch(source_id=source_id)
    payments = list(
        OfferingPayment.objects.filter(
            household_uid=household_id,
        )
        .select_related("household", "person", "service_schedule")
        .order_by("-received_on", "-id")
    )
    category_filter = _normalize_payment_category_filter(payment_category_filter)
    person_filter = _normalize_payment_person_filter(payment_person_filter, payments)
    filtered_payments = [
        payment
        for payment in payments
        if _payment_matches_filters(
            payment,
            payment_category_filter=category_filter,
            payment_person_filter=person_filter,
        )
    ]
    entries = [
        build_offering_payment_entry(
            payment,
            current_url=current_url,
            household_id=household_id,
        )
        for payment in filtered_payments
    ]
    total_amount = sum((payment.amount or Decimal("0") for payment in filtered_payments), start=Decimal("0"))
    unfiltered_total_amount = sum((payment.amount or Decimal("0") for payment in payments), start=Decimal("0"))
    return {
        "count": len(filtered_payments),
        "total_amount": total_amount,
        "unfiltered_count": len(payments),
        "unfiltered_total_amount": unfiltered_total_amount,
        "active_filters": _payment_active_filters(
            payments,
            current_url=current_url,
            household_id=household_id,
            payment_category_filter=category_filter,
            payment_person_filter=person_filter,
        ),
        "clear_filter_url": household_payment_filter_url(
            current_url=current_url,
            household_id=household_id,
            payment_category="",
            payment_person="",
        ),
    }, entries


def build_offering_payment_entry(
    payment: OfferingPayment,
    *,
    current_url: str,
    household_id: str | None = None,
    linked_service_items: list[str] | None = None,
) -> dict:
    linked_items = linked_service_items or []
    is_temple_event = _payment_is_temple_event(payment)
    service_url = payment_service_edit_url(payment, current_url=current_url)
    payment_url = payment_standalone_edit_url(payment, current_url=current_url)
    payer_label = _payment_payer_label(payment) if is_temple_event else ""
    person_label = payer_label if is_temple_event else _payment_person_label(payment)
    person_id = _payment_person_id(payment)
    category_label = payment.get_payment_category_display()
    method_label = payment.get_payment_method_display()
    service_label = (
        payment.service_schedule.service_label
        if payment.service_schedule_id and payment.service_schedule is not None
        else "法要外"
    )
    return {
        "payment_id": payment.pk,
        "received_on": payment.received_on.isoformat(),
        "received_on_short": f"{payment.received_on.day}日",
        "received_on_month_day": f"{payment.received_on.month}月{payment.received_on.day}日",
        "household_name": _payment_household_name(payment),
        "household_url": _payment_household_url(payment),
        "person_label": person_label,
        "person_name": person_label,
        "person_id": person_id,
        "payer_label": payer_label,
        "is_temple_event": is_temple_event,
        "service_label": service_label,
        "service_kind_label": (
            "寺予定" if is_temple_event else "法要" if payment.service_schedule_id else "法要外"
        ),
        "is_service_linked": bool(payment.service_schedule_id),
        "service_edit_url": service_url,
        "service_url": service_url,
        "payment_edit_url": payment_url,
        "linked_service_items": linked_items,
        "category_label": category_label,
        "payment_category_label": category_label,
        "category_filter_url": household_payment_filter_url(
            current_url=current_url,
            household_id=household_id or _payment_household_id(payment),
            payment_category=payment.payment_category,
        ),
        "person_filter_url": (
            ""
            if is_temple_event
            else household_payment_filter_url(
                current_url=current_url,
                household_id=household_id or _payment_household_id(payment),
                payment_person=person_id or HOUSEHOLD_PAYMENT_PERSON_FILTER_VALUE,
            )
        ),
        "method_label": method_label,
        "payment_method_label": method_label,
        "amount": payment.amount or Decimal("0"),
        "received_by": (payment.received_by or "").strip(),
        "notes": (payment.notes or "").strip(),
    }


def household_payment_filter_url(
    *,
    current_url: str,
    household_id: str,
    payment_category: str | None = None,
    payment_person: str | None = None,
) -> str:
    if not household_id:
        return ""
    split_url = urlsplit(current_url)
    params = [
        (key, value)
        for key, value in parse_qsl(split_url.query, keep_blank_values=True)
        if key not in {"household_id", "focus"}
        and (payment_category is None or key != "payment_category")
        and (payment_person is None or key != "payment_person")
    ]
    params.append(("household_id", household_id))
    params.append(("focus", "detail"))
    if payment_category:
        params.append(("payment_category", payment_category))
    if payment_person:
        params.append(("payment_person", payment_person))
    return urlunsplit(
        (
            split_url.scheme,
            split_url.netloc,
            split_url.path or reverse("office:household_browser"),
            urlencode(params),
            split_url.fragment,
        )
    )


def _normalize_payment_category_filter(value: str) -> str:
    value = (value or "").strip()
    valid_values = {choice_value for choice_value, _label in OfferingPayment.Category.choices}
    if value in valid_values:
        return value
    return ""


def _normalize_payment_person_filter(value: str, payments: list[OfferingPayment]) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value == HOUSEHOLD_PAYMENT_PERSON_FILTER_VALUE:
        return value if any(not _payment_person_id(payment) for payment in payments) else ""
    person_ids = {_payment_person_id(payment) for payment in payments}
    return value if value in person_ids else ""


def _payment_matches_filters(
    payment: OfferingPayment,
    *,
    payment_category_filter: str,
    payment_person_filter: str,
) -> bool:
    if payment_category_filter and payment.payment_category != payment_category_filter:
        return False
    if payment_person_filter:
        person_id = _payment_person_id(payment)
        if payment_person_filter == HOUSEHOLD_PAYMENT_PERSON_FILTER_VALUE:
            return not person_id
        return person_id == payment_person_filter
    return True


def _payment_active_filters(
    payments: list[OfferingPayment],
    *,
    current_url: str,
    household_id: str,
    payment_category_filter: str,
    payment_person_filter: str,
) -> list[dict[str, str]]:
    active_filters = []
    if payment_category_filter:
        active_filters.append(
            {
                "label": "区分",
                "value": dict(OfferingPayment.Category.choices).get(
                    payment_category_filter,
                    payment_category_filter,
                ),
                "clear_url": household_payment_filter_url(
                    current_url=current_url,
                    household_id=household_id,
                    payment_category="",
                ),
            }
        )
    if payment_person_filter:
        active_filters.append(
            {
                "label": "対象者",
                "value": _payment_person_filter_label(payment_person_filter, payments),
                "clear_url": household_payment_filter_url(
                    current_url=current_url,
                    household_id=household_id,
                    payment_person="",
                ),
            }
        )
    return active_filters


def _payment_person_filter_label(value: str, payments: list[OfferingPayment]) -> str:
    if value == HOUSEHOLD_PAYMENT_PERSON_FILTER_VALUE:
        return "家全体"
    for payment in payments:
        if _payment_person_id(payment) == value:
            return _payment_person_label(payment)
    return value


def household_offering_payment_create_url(*, household_id: str, current_url: str) -> str:
    return (
        f"{reverse('office:create_household_offering_payment', args=[household_id])}"
        f"?{urlencode({'next': current_url})}"
    )


def person_offering_payment_create_url(
    *,
    household_id: str,
    person_id: str,
    current_url: str,
) -> str:
    return (
        f"{reverse('office:create_person_offering_payment', args=[household_id, person_id])}"
        f"?{urlencode({'next': current_url})}"
    )


def payment_standalone_edit_url(payment: OfferingPayment, *, current_url: str) -> str:
    if payment.service_schedule_id or not payment.pk:
        return ""
    household_id = _payment_household_id(payment)
    if not household_id:
        return ""
    return (
        f"{reverse('office:edit_household_offering_payment', args=[household_id, payment.pk])}"
        f"?{urlencode({'next': current_url})}"
    )


def payment_service_edit_url(payment: OfferingPayment, *, current_url: str) -> str:
    if not payment.service_schedule_id or payment.service_schedule is None:
        return ""
    if _payment_is_temple_event(payment):
        return (
            f"{reverse('office:edit_temple_event', kwargs={'event_id': payment.service_schedule_id})}"
            f"?{urlencode({'next': current_url})}"
        )
    household_id = (payment.service_schedule.household_uid or "").strip()
    event_id = (payment.service_schedule.schedule_uid or "").strip()
    if not household_id or not event_id:
        return ""
    return (
        f"{reverse('office:edit_service_schedule', args=[household_id, event_id])}"
        f"?{urlencode({'next': current_url})}"
    )


def payment_sort_key(payment: OfferingPayment) -> tuple:
    schedule = payment.service_schedule if payment.service_schedule_id else None
    service_date = _payment_service_sort_date(payment)
    service_time = schedule.scheduled_time.isoformat() if schedule and schedule.scheduled_time else ""
    service_label = schedule.service_label if schedule else ""
    household_id = schedule.household_uid if schedule and schedule.household_uid else payment.household_uid
    person_id = schedule.person_uid if schedule and schedule.person_uid else payment.person_uid
    return (
        payment.received_on.month,
        0 if schedule else 1,
        service_date,
        service_time,
        household_id or "",
        person_id or "",
        service_label,
        int(schedule.pk) if schedule and schedule.pk else 0,
        _payment_category_rank(payment.payment_category),
        payment.received_on,
        int(payment.pk) if payment.pk else 0,
    )


def linked_schedules_by_group(
    batch: ImportBatch,
    payments: list[OfferingPayment],
    *,
    canonical_population_checked: bool = False,
) -> dict[str, list[ServiceSchedule]]:
    if not canonical_population_checked:
        canonical_population.canonical_provenance_import_batch(
            source_id=batch.source.source_id,
        )
    link_group_keys = {
        payment.service_schedule.link_group_key
        for payment in payments
        if payment.service_schedule_id
        and payment.service_schedule is not None
        and payment.service_schedule.link_group_key
    }
    if not link_group_keys:
        return {}
    schedules = list(
        ServiceSchedule.objects.filter(
            deleted_at__isnull=True,
            link_group_key__in=sorted(link_group_keys),
        )
        .select_related("person")
        .order_by("id")
    )
    grouped: dict[str, list[ServiceSchedule]] = {}
    for schedule in schedules:
        if not schedule.link_group_key:
            continue
        grouped.setdefault(schedule.link_group_key, []).append(schedule)
    return grouped


def payment_linked_service_items(
    payment: OfferingPayment,
    linked_schedules_by_group: dict[str, list[ServiceSchedule]],
) -> list[str]:
    if (
        not payment.service_schedule_id
        or payment.service_schedule is None
        or not payment.service_schedule.link_group_key
    ):
        return []
    linked = [
        item
        for item in linked_schedules_by_group.get(payment.service_schedule.link_group_key, [])
        if item.pk != payment.service_schedule_id
    ]
    if not linked:
        return []
    return [
        f"{item.subject_name or item.person_name_snapshot or item.person_uid} {item.service_label}"
        for item in linked
    ]


def snapshot_service_schedule_payments(
    schedule: ServiceSchedule,
) -> tuple[dict[int, dict], dict[int, OfferingPayment]]:
    from apps.office.services.record_history_snapshot import _serialize_offering_payment_record

    payments = list(
        OfferingPayment.objects.filter(service_schedule=schedule)
        .select_related("household", "person", "service_schedule")
        .order_by("pk")
    )
    return (
        {payment.pk: _serialize_offering_payment_record(payment) for payment in payments if payment.pk is not None},
        {payment.pk: payment for payment in payments if payment.pk is not None},
    )


def create_offering_payment_logs_for_diff(
    *,
    before_snapshots: dict[int, dict],
    before_records: dict[int, OfferingPayment],
    after_payments: list[OfferingPayment],
    editor_label: str,
    change_note: str,
) -> list:
    from apps.imports.models import RecordEditLog
    from apps.office.services.record_history_mutations import _create_record_edit_log
    from apps.office.services.record_history_snapshot import _serialize_offering_payment_record

    logs = []
    after_by_pk = {payment.pk: payment for payment in after_payments if payment.pk is not None}
    after_snapshots = {
        payment.pk: _serialize_offering_payment_record(payment)
        for payment in after_payments
        if payment.pk is not None
    }
    all_pks = sorted(set(before_snapshots) | set(after_snapshots))
    for payment_pk in all_pks:
        before_data = before_snapshots.get(payment_pk, {})
        after_data = after_snapshots.get(payment_pk, {})
        if before_data == after_data:
            continue
        if payment_pk in after_by_pk:
            record = after_by_pk[payment_pk]
            action_kind = None
        else:
            record = before_records[payment_pk]
            action_kind = RecordEditLog.ActionKind.DELETE
        log_entry = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.OFFERING_PAYMENT,
            record=record,
            before_data=before_data,
            after_data=after_data,
            editor_label=editor_label,
            change_note=change_note,
            action_kind=action_kind,
        )
        if log_entry is not None:
            logs.append(log_entry)
    return logs


def _attach_member_payment_url(
    member: dict,
    *,
    household_id: str,
    current_url: str,
) -> dict:
    person_id = str(member.get("person_id") or "").strip()
    if not person_id:
        return dict(member)
    return {
        **member,
        "new_payment_url": person_offering_payment_create_url(
            household_id=household_id,
            person_id=person_id,
            current_url=current_url,
        ),
    }


def _payment_household_id(payment: OfferingPayment) -> str:
    if payment.household_id and payment.household is not None:
        return (payment.household.household_uid or "").strip()
    return (payment.household_uid or "").strip()


def _payment_person_id(payment: OfferingPayment) -> str:
    if payment.person_id and payment.person is not None:
        return (payment.person.person_uid or "").strip()
    return (payment.person_uid or "").strip()


def _payment_household_name(payment: OfferingPayment) -> str:
    snapshot_name = (payment.household_name_snapshot or "").strip()
    if snapshot_name:
        if snapshot_name.startswith("仮戸主") and payment.household_id and payment.household is not None:
            current_name = (payment.household.display_head_name() or "").strip()
            if current_name and current_name != snapshot_name:
                return current_name
        return snapshot_name
    if payment.household_id and payment.household is not None:
        return payment.household.display_head_name()
    return payment.household_uid


def _payment_person_label(payment: OfferingPayment) -> str:
    if payment.person_name_snapshot:
        return payment.person_name_snapshot
    if payment.person_id and payment.person is not None:
        return payment.person.name or payment.person.person_uid
    return "家全体"


def _payment_is_temple_event(payment: OfferingPayment) -> bool:
    return bool(
        payment.service_schedule_id
        and payment.service_schedule is not None
        and payment.service_schedule.event_scope == ServiceSchedule.EventScope.TEMPLE
    )


def _payment_payer_label(payment: OfferingPayment) -> str:
    return (payment.payer_name or "").strip() or _payment_household_name(payment) or "匿名"


def _payment_household_url(payment: OfferingPayment) -> str:
    household_id = _payment_household_id(payment)
    if not household_id:
        return ""
    return f"{reverse('office:household_browser')}?{urlencode({'household_id': household_id})}"


def _payment_service_sort_date(payment: OfferingPayment):
    if not payment.service_schedule_id or payment.service_schedule is None:
        return payment.received_on
    schedule = payment.service_schedule
    return schedule.completed_on or schedule.scheduled_date or schedule.target_date or payment.received_on


def _payment_category_rank(payment_category: str) -> int:
    for index, (value, _label) in enumerate(OfferingPayment.Category.choices):
        if value == payment_category:
            return index
    return len(OfferingPayment.Category.choices)
