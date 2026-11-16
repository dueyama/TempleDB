from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import ImportedOperationalMixin, OfferingPayment, ServiceSchedule


HOUSEHOLD_ONLY_SERVICE_LABELS = {
    "bon": "盆",
    "otokoshi": "お取越し",
}


def _extend_update_fields(kwargs: dict[str, Any], fields: set[str]) -> None:
    update_fields = kwargs.get("update_fields")
    if update_fields is not None:
        kwargs["update_fields"] = [*set(update_fields).union(fields)]


def sync_imported_operational_references(record: ImportedOperationalMixin) -> None:
    if getattr(record, "event_scope", "") == "temple" and not record.household_id:
        record.household_uid = ""
        record.household_name_snapshot = ""
    if record.person_id and record.person and not record.household_id:
        record.household = record.person.household

    if record.household_id and record.household:
        record.related_batch = record.household.batch
        record.legacy_source_id = record.household.legacy_source_id
        record.household_uid = record.household.household_uid
        record.household_name_snapshot = record.household.display_head_name()

    if record.person_id and record.person:
        record.related_batch = record.person.batch
        record.legacy_source_id = record.person.legacy_source_id or record.legacy_source_id
        record.person_uid = record.person.person_uid
        record.household_uid = record.person.household.household_uid or record.household_uid
        record.person_name_snapshot = record.person.name
        if not record.household_name_snapshot and record.person.household_id:
            record.household_name_snapshot = record.person.household.display_head_name()


def save_imported_operational_record(
    record: ImportedOperationalMixin,
    owner_cls: type[ImportedOperationalMixin],
    *args: Any,
    **kwargs: Any,
):
    record._sync_import_references()
    return super(owner_cls, record).save(*args, **kwargs)


def save_service_schedule(
    schedule: ServiceSchedule,
    owner_cls: type[ServiceSchedule],
    *args: Any,
    **kwargs: Any,
):
    household_only_label = HOUSEHOLD_ONLY_SERVICE_LABELS.get(
        str(getattr(schedule, "category", "") or "").strip(),
        "",
    )
    if household_only_label:
        schedule.service_label = household_only_label
        schedule.person = None
        schedule.person_uid = ""
        schedule.person_name_snapshot = ""
        schedule.subject_name = ""
        schedule.target_date = None
        schedule.link_group_key = ""
        _extend_update_fields(
            kwargs,
            {
                "service_label",
                "person",
                "person_uid",
                "person_name_snapshot",
                "subject_name",
                "target_date",
                "link_group_key",
            },
        )
    is_generic_other_event = (
        bool(household_only_label)
        or (
            str(getattr(schedule, "category", "") or "").strip() == "other"
            and str(getattr(schedule, "service_label", "") or "").strip() != "葬儀"
        )
    )
    if schedule.person_id and schedule.person and not schedule.subject_name and not is_generic_other_event:
        schedule.subject_name = schedule.person.name
    return super(owner_cls, schedule).save(*args, **kwargs)


def sync_offering_payment_references(payment: OfferingPayment) -> None:
    if payment.service_schedule_id and payment.service_schedule:
        # A temple event's related household is not necessarily its donor.
        if payment.service_schedule.event_scope != "temple":
            if not payment.household_id:
                payment.household = payment.service_schedule.household
            if not payment.person_id:
                payment.person = payment.service_schedule.person
        else:
            payment.related_batch = payment.service_schedule.related_batch
            payment.legacy_source_id = payment.service_schedule.legacy_source_id
            if not payment.household_id:
                payment.household_uid = ""
                payment.household_name_snapshot = ""
    sync_imported_operational_references(payment)
