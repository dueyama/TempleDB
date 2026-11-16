from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from django.urls import reverse

from apps.imports.models import ServiceSchedule

_SERVICE_STATUS_LABELS = {
    ServiceSchedule.Status.CANDIDATE: ServiceSchedule.Status.CANDIDATE.label,
    ServiceSchedule.Status.SCHEDULED: ServiceSchedule.Status.SCHEDULED.label,
    ServiceSchedule.Status.COMPLETED: ServiceSchedule.Status.COMPLETED.label,
    ServiceSchedule.Status.CANCELLED: ServiceSchedule.Status.CANCELLED.label,
    ServiceSchedule.Status.DEFERRED: ServiceSchedule.Status.DEFERRED.label,
}


def attach_household_browser_event_history_context(
    context: dict,
    *,
    current_url: str,
) -> None:
    detail = context.get("detail")
    if not detail:
        return

    household_id = str(detail.get("summary", {}).get("household_id") or "").strip()
    if not household_id:
        return

    data_backend = str(context.get("data_backend") or "").strip()
    head_person_id = str(detail.get("head_person_id") or "").strip()
    detail["head_other_event_url"] = _head_other_event_url(
        household_id=household_id,
        head_person_id=head_person_id,
        current_url=current_url,
        data_backend=data_backend,
    )

    entries = [
        _build_household_event_history_entry(
            item,
            household_id=household_id,
            current_url=current_url,
            include_edit_url=data_backend == "db",
        )
        for item in detail.get("events", [])
        if isinstance(item, dict)
    ]
    entries.sort(
        key=lambda item: (
            item["sort_has_date"],
            item["sort_date_value"],
            item["sort_event_key"],
        ),
        reverse=True,
    )
    for item in entries:
        item.pop("sort_has_date", None)
        item.pop("sort_date_value", None)
        item.pop("sort_event_key", None)

    detail["event_history_entries"] = entries
    detail["event_history_count"] = len(entries)


def _head_other_event_url(
    *,
    household_id: str,
    head_person_id: str,
    current_url: str,
    data_backend: str,
) -> str:
    if data_backend != "db" or not household_id or not head_person_id:
        return ""
    return (
        f"{reverse('office:create_service_schedule', args=[household_id, head_person_id])}"
        f"?{urlencode({'category': ServiceSchedule.Category.OTHER, 'next': current_url})}"
    )


def _build_household_event_history_entry(
    item: dict,
    *,
    household_id: str,
    current_url: str,
    include_edit_url: bool,
) -> dict:
    completed_on = str(item.get("completed_on") or "").strip()
    scheduled_date = str(item.get("scheduled_date") or "").strip()
    target_date = str(item.get("target_date") or "").strip()
    event_id = str(item.get("event_id") or "").strip()
    source_table = str(item.get("source_table") or "").strip()
    event_scope = str(item.get("event_scope") or "").strip()
    sort_date = _parse_iso_date(completed_on) or _parse_iso_date(scheduled_date)
    status_label = str(item.get("status_label") or "").strip()
    if not status_label:
        status_label = _SERVICE_STATUS_LABELS.get(str(item.get("status") or "").strip(), "")
    title = (
        str(item.get("schedule_type") or "").strip()
        or str(item.get("service_label") or "").strip()
        or "名称未設定"
    )

    if completed_on:
        display_date = completed_on
        display_date_label = "実施日"
    elif scheduled_date:
        display_date = scheduled_date
        display_date_label = "予定日"
    else:
        display_date = target_date
        display_date_label = "基準日" if target_date else ""

    return {
        "title": title,
        "date": display_date,
        "date_label": display_date_label,
        "status_label": status_label,
        "subject_name": str(item.get("subject_name") or "").strip(),
        "note": str(item.get("note") or "").strip(),
        "event_id": event_id,
        "source_table": source_table,
        "is_temple_event": event_scope == ServiceSchedule.EventScope.TEMPLE,
        "edit_url": _event_edit_url(
            household_id=household_id,
            event_id=event_id,
            source_table=source_table,
            current_url=current_url,
            include_edit_url=include_edit_url,
            event_scope=event_scope,
            schedule_pk=item.get("schedule_pk"),
        ),
        "sort_has_date": 1 if sort_date is not None else 0,
        "sort_date_value": sort_date.toordinal() if sort_date is not None else -1,
        "sort_event_key": event_id or title,
    }


def _event_edit_url(
    *,
    household_id: str,
    event_id: str,
    source_table: str,
    current_url: str,
    include_edit_url: bool,
    event_scope: str = "",
    schedule_pk: object = None,
) -> str:
    if include_edit_url and event_scope == ServiceSchedule.EventScope.TEMPLE:
        try:
            temple_event_id = int(str(schedule_pk))
        except (TypeError, ValueError):
            return ""
        if temple_event_id <= 0:
            return ""
        path = reverse("office:edit_temple_event", kwargs={"event_id": temple_event_id})
        return f"{path}?{urlencode({'next': current_url})}"
    if not include_edit_url or not household_id or not event_id:
        return ""
    query = {"next": current_url}
    if source_table:
        query["source_table"] = source_table
    return f"{reverse('office:edit_service_schedule', args=[household_id, event_id])}?{urlencode(query)}"


def _parse_iso_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


__all__ = ["attach_household_browser_event_history_context"]
