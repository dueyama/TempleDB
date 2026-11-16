from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from apps.imports import service_ledger_runtime
from apps.imports.forms import OfferingPaymentFormSet
from apps.imports.models import OfferingPayment, Person, ServiceSchedule
from apps.imports.service_ledger_candidate_entries import _matching_actual_schedule_for_candidate
from apps.imports.service_ledger_schedule_entries import _is_actual_service_schedule


def find_existing_memorial_candidate_schedule(
    person: Person, *, category: str, service_label: str, target_date: str,
) -> ServiceSchedule | None:
    """Resolve a stale candidate link without using its date as the scheduled date."""
    if (
        category not in {
            ServiceSchedule.Category.MEMORIAL, ServiceSchedule.Category.CHUIN,
            ServiceSchedule.Category.HATSUBON,
        }
        or not service_label.strip()
        or _parse_prefill_date(target_date) is None
    ):
        return None
    schedules = ServiceSchedule.objects.select_related("person__deceased_profile").filter(
        person=person, household=person.household, category=category, deleted_at__isnull=True,
    ).exclude(
        status__in=[ServiceSchedule.Status.CANCELLED, ServiceSchedule.Status.DEFERRED],
    ).order_by("-pk")
    return _matching_actual_schedule_for_candidate(
        {"person_id": person.person_uid, "label": service_label.strip(), "target_date": target_date},
        [schedule for schedule in schedules if _is_actual_service_schedule(schedule)],
    )


def _is_generic_other_service_schedule(
    category: str | None,
    service_label: str | None = None,
) -> bool:
    normalized_category = str(category or "").strip()
    normalized_label = str(service_label or "").strip()
    return _is_household_only_service_schedule(normalized_category) or (
        normalized_category == ServiceSchedule.Category.OTHER and normalized_label != "葬儀"
    )


def _is_household_only_service_schedule(category: str | None) -> bool:
    return bool(_household_only_service_schedule_label(category))


def _household_only_service_schedule_label(category: str | None) -> str:
    normalized_category = str(category or "").strip()
    if normalized_category == ServiceSchedule.Category.BON:
        return ServiceSchedule.Category.BON.label
    if normalized_category == ServiceSchedule.Category.OTOKOSHI:
        return ServiceSchedule.Category.OTOKOSHI.label
    return ""


def _service_schedule_for_edit(schedule_pk: int) -> ServiceSchedule:
    return ServiceSchedule.objects.select_related("household", "person", "person__deceased_profile").get(pk=schedule_pk)


def _new_manual_service_schedule(batch, person: Person) -> ServiceSchedule:
    household = person.household if person.household_id else None
    return ServiceSchedule(
        related_batch=batch,
        household=household,
        person=person,
        legacy_source_id=person.legacy_source_id,
        household_uid=household.household_uid if household is not None else "",
        person_uid=person.person_uid,
        household_name_snapshot=household.head_name if household is not None else "",
        person_name_snapshot=person.name,
        is_demo_data=False,
        record_origin=ServiceSchedule.Origin.MANUAL,
        source_export_batch=batch.prepared_snapshot_id,
        source_table="manual_service_schedule",
        category=ServiceSchedule.Category.MEMORIAL,
        service_label="",
        subject_name=person.name,
        status=ServiceSchedule.Status.SCHEDULED,
    )


def _apply_manual_service_schedule_defaults(schedule: ServiceSchedule, batch, person: Person) -> None:
    schedule.related_batch = batch
    schedule.household = person.household if person.household_id else schedule.household
    schedule.person = person
    schedule.is_demo_data = False
    schedule.record_origin = ServiceSchedule.Origin.MANUAL
    schedule.source_export_batch = batch.prepared_snapshot_id
    schedule.source_table = schedule.source_table or "manual_service_schedule"
    household_only_label = _household_only_service_schedule_label(schedule.category)
    if household_only_label:
        schedule.service_label = household_only_label
        schedule.person = None
        schedule.person_uid = ""
        schedule.person_name_snapshot = ""
        schedule.subject_name = ""
    elif _is_generic_other_service_schedule(schedule.category, schedule.service_label):
        schedule.subject_name = ""
    elif not schedule.subject_name:
        schedule.subject_name = person.name


def apply_service_schedule_prefill_values(
    schedule: ServiceSchedule,
    *,
    category: str,
    service_label: str,
    target_date: str,
) -> None:
    if category in {choice for choice, _label in ServiceSchedule.Category.choices}:
        schedule.category = category
    household_only_label = _household_only_service_schedule_label(schedule.category)
    if household_only_label:
        schedule.service_label = household_only_label
    elif service_label:
        schedule.service_label = service_label
    scheduled_date = (
        _parse_prefill_date(target_date)
        or service_ledger_runtime._resolved_service_schedule_target_date(schedule)
    )
    if schedule.scheduled_date is None and scheduled_date is not None:
        schedule.scheduled_date = scheduled_date
    if schedule.scheduled_time is None:
        schedule.scheduled_time = time(hour=10, minute=0)


def _parse_prefill_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _prepare_service_schedule_post_data(post_data, action: str):
    updated = post_data.copy()
    completed_on = str(updated.get("completed_on", "") or "").strip()
    scheduled_date = str(updated.get("scheduled_date", "") or "").strip()
    status = str(updated.get("status", "") or "").strip()
    if action == "complete_save":
        updated["status"] = ServiceSchedule.Status.COMPLETED
        status = ServiceSchedule.Status.COMPLETED
    if not completed_on and status == ServiceSchedule.Status.COMPLETED:
        completed_date = _parse_prefill_date(scheduled_date) or timezone.localdate()
        updated["completed_on"] = completed_date.isoformat()
    return updated


def _service_payment_formset(
    *,
    data=None,
    schedule: ServiceSchedule,
    prefix: str = "payments",
):
    if data is not None and f"{prefix}-TOTAL_FORMS" not in data:
        data = data.copy()
        data[f"{prefix}-TOTAL_FORMS"] = "0"
        data[f"{prefix}-INITIAL_FORMS"] = "0"
        data[f"{prefix}-MIN_NUM_FORMS"] = "0"
        data[f"{prefix}-MAX_NUM_FORMS"] = "1000"
    queryset = (
        OfferingPayment.objects.none()
        if not getattr(schedule, "pk", None)
        else OfferingPayment.objects.filter(service_schedule=schedule).order_by(
            "received_on",
            "payment_category",
            "pk",
        )
    )
    formset = OfferingPaymentFormSet(
        data=data,
        instance=schedule,
        prefix=prefix,
        queryset=queryset,
    )
    schedule_date = schedule.scheduled_date or schedule.completed_on or timezone.localdate()
    for form in formset.forms:
        if not getattr(form.instance, "pk", None) and not form.initial.get("received_on"):
            form.fields["received_on"].initial = schedule_date
    return formset


def _service_payment_summary(schedule: ServiceSchedule) -> list[dict]:
    rows = (
        OfferingPayment.objects.filter(service_schedule=schedule)
        .order_by("payment_category")
        .values("payment_category")
        .annotate(total=Sum("amount"), count=Count("id"))
    )
    return [
        {
            "label": dict(OfferingPayment.Category.choices).get(row["payment_category"], row["payment_category"]),
            "total": row["total"] or Decimal("0"),
            "count": row["count"],
        }
        for row in rows
    ]


def _normalize_service_schedule_target_date(schedule: ServiceSchedule) -> None:
    if schedule.category in {
        ServiceSchedule.Category.MEMORIAL,
        ServiceSchedule.Category.CHUIN,
        ServiceSchedule.Category.HATSUBON,
        ServiceSchedule.Category.FUNERAL,
        ServiceSchedule.Category.BON,
        ServiceSchedule.Category.OTOKOSHI,
    }:
        schedule.target_date = None


def _normalize_service_schedule_subject_name(schedule: ServiceSchedule) -> None:
    household_only_label = _household_only_service_schedule_label(schedule.category)
    if household_only_label:
        schedule.service_label = household_only_label
        schedule.person = None
        schedule.person_uid = ""
        schedule.person_name_snapshot = ""
        schedule.subject_name = ""
    elif _is_generic_other_service_schedule(schedule.category, schedule.service_label):
        schedule.subject_name = ""


def _persist_manual_service_schedule_identity(schedule: ServiceSchedule) -> None:
    update_fields: list[str] = []
    if not schedule.schedule_uid:
        schedule.schedule_uid = f"manual-{schedule.pk}"
        update_fields.append("schedule_uid")
    if not schedule.legacy_pk_text:
        schedule.legacy_pk_text = schedule.schedule_uid
        update_fields.append("legacy_pk_text")
    if schedule.source_table != "manual_service_schedule":
        schedule.source_table = "manual_service_schedule"
        update_fields.append("source_table")
    if update_fields:
        schedule.save(update_fields=[*update_fields, "updated_at"])
