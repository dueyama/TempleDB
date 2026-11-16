from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from apps.imports.models import (
    DistrictMemberSheetState,
    HandDeliveryReviewResolution,
    Household,
    ImportBatch,
    Person,
    PostalReviewResolution,
    ServiceSchedule,
    VisitNote,
)

from .memo_search_assignments import _assignment_map
from .memo_search_entry_support import _build_entry, _safe_household_name
from .memo_search_scope import (
    _scoped_households,
    _scoped_people,
    _scoped_service_schedules,
    _scoped_visit_notes,
)
from .memo_search_shared import NOTE_TYPE_DEFINITIONS, _date_to_text


def _memo_entries(
    *,
    source_id: str,
    visible_batch: ImportBatch | None,
    include_history: bool,
    note_types: set[str] | None = None,
    date_from: str = "",
    date_to: str = "",
    include_assignments: bool = True,
) -> list[dict[str, Any]]:
    assignment_map = _assignment_map() if include_assignments else {}
    entries: list[dict[str, Any]] = []
    content_types = ContentType.objects.get_for_models(
        Household,
        Person,
        ServiceSchedule,
        VisitNote,
        PostalReviewResolution,
        HandDeliveryReviewResolution,
        DistrictMemberSheetState,
    )

    household_type = content_types[Household]
    include_household_note = note_types is None or "household_note" in note_types
    for household in _scoped_households(
        source_id=source_id,
        visible_batch=visible_batch,
        include_history=include_history,
    ).order_by("-updated_at", "-id"):
        if not include_household_note:
            break
        if not (household.notes or "").strip():
            continue
        entries.append(
            _build_entry(
                content_type_id=household_type.id,
                object_id=household.id,
                field_name="notes",
                note_type="household_note",
                note_label=NOTE_TYPE_DEFINITIONS["household_note"]["label"],
                title=_safe_household_name(household),
                text=household.notes,
                updated_at=household.updated_at,
                household_id=household.household_uid,
                household_name=_safe_household_name(household),
                person_id="",
                person_name="",
                schedule_id="",
                legacy_source_id=household.legacy_source_id,
                legacy_household_id=household.household_uid,
                legacy_person_id="",
                legacy_schedule_id="",
                action_url=reverse("office:edit_household", args=[household.household_uid]),
                action_label="この家を修正",
                batch_snapshot_id=household.batch.prepared_snapshot_id if household.batch_id else "",
                assignment_map=assignment_map,
            )
        )

    person_type = content_types[Person]
    include_person_note = note_types is None or "person_note" in note_types
    include_deceased_note = note_types is None or "deceased_note" in note_types
    people = _scoped_people(
        source_id=source_id,
        visible_batch=visible_batch,
        include_history=include_history,
    ).order_by("-updated_at", "-id")
    for person in people:
        household_name = _safe_household_name(person.household)
        household_uid = person.household.household_uid
        if include_person_note and (person.person_note or "").strip():
            entries.append(
                _build_entry(
                    content_type_id=person_type.id,
                    object_id=person.id,
                    field_name="person_note",
                    note_type="person_note",
                    note_label=NOTE_TYPE_DEFINITIONS["person_note"]["label"],
                    title=person.name,
                    text=person.person_note,
                    updated_at=person.updated_at,
                    household_id=household_uid,
                    household_name=household_name,
                    person_id=person.person_uid,
                    person_name=person.name,
                    schedule_id="",
                    legacy_source_id=person.legacy_source_id,
                    legacy_household_id=household_uid,
                    legacy_person_id=person.person_uid,
                    legacy_schedule_id="",
                    action_url=reverse(
                        "office:edit_person",
                        args=[household_uid, person.person_uid],
                    ),
                    action_label="この人を修正",
                    batch_snapshot_id=person.batch.prepared_snapshot_id if person.batch_id else "",
                    assignment_map=assignment_map,
                )
            )
        if include_deceased_note and (person.deceased_note or "").strip():
            entries.append(
                _build_entry(
                    content_type_id=person_type.id,
                    object_id=person.id,
                    field_name="deceased_note",
                    note_type="deceased_note",
                    note_label=NOTE_TYPE_DEFINITIONS["deceased_note"]["label"],
                    title=person.name,
                    text=person.deceased_note,
                    updated_at=person.updated_at,
                    household_id=household_uid,
                    household_name=household_name,
                    person_id=person.person_uid,
                    person_name=person.name,
                    schedule_id="",
                    legacy_source_id=person.legacy_source_id,
                    legacy_household_id=household_uid,
                    legacy_person_id=person.person_uid,
                    legacy_schedule_id="",
                    action_url=reverse(
                        "office:edit_person",
                        args=[household_uid, person.person_uid],
                    ),
                    action_label="この人を修正",
                    batch_snapshot_id=person.batch.prepared_snapshot_id if person.batch_id else "",
                    assignment_map=assignment_map,
                )
            )

    schedule_type = content_types[ServiceSchedule]
    include_schedule_note = note_types is None or "service_schedule_note" in note_types
    schedules = _scoped_service_schedules(
        source_id=source_id,
        visible_batch=visible_batch,
        include_history=include_history,
    )
    if date_from:
        schedules = schedules.filter(scheduled_date__gte=date_from)
    if date_to:
        schedules = schedules.filter(scheduled_date__lte=date_to)
    schedules = schedules.order_by("-updated_at", "-id")
    for schedule in schedules:
        if not include_schedule_note:
            break
        if not (schedule.notes or "").strip():
            continue
        household_name = (
            _safe_household_name(schedule.household)
            if schedule.household_id
            else (schedule.household_name_snapshot or schedule.household_uid)
        )
        person_name = (
            schedule.person.name
            if schedule.person_id
            else (schedule.person_name_snapshot or schedule.subject_name)
        )
        schedule_uid = schedule.schedule_uid
        if schedule.event_scope == ServiceSchedule.EventScope.TEMPLE:
            action_url = reverse("office:edit_temple_event", kwargs={"event_id": schedule.pk})
            action_label = "この寺予定を修正"
        elif schedule.household_uid and schedule_uid:
            action_url = reverse(
                "office:edit_service_schedule",
                args=[schedule.household_uid, schedule_uid],
            )
            action_label = "この予定を修正"
        else:
            action_url = reverse("office:service_ledger")
            action_label = "法要台帳を開く"
        entries.append(
            _build_entry(
                content_type_id=schedule_type.id,
                object_id=schedule.id,
                field_name="notes",
                note_type="service_schedule_note",
                note_label=NOTE_TYPE_DEFINITIONS["service_schedule_note"]["label"],
                title=schedule.service_label,
                text=schedule.notes,
                updated_at=schedule.updated_at,
                household_id=schedule.household_uid,
                household_name=household_name,
                person_id=schedule.person_uid,
                person_name=person_name,
                schedule_id=schedule_uid,
                legacy_source_id=schedule.legacy_source_id,
                legacy_household_id=schedule.household_uid,
                legacy_person_id=schedule.person_uid,
                legacy_schedule_id=schedule.schedule_uid,
                action_url=action_url,
                action_label=action_label,
                event_date=_date_to_text(schedule.scheduled_date or schedule.target_date),
                batch_snapshot_id=(
                    schedule.related_batch.prepared_snapshot_id if schedule.related_batch_id else ""
                ),
                assignment_map=assignment_map,
            )
        )

    visit_note_type = content_types[VisitNote]
    include_visit_body = note_types is None or "visit_note_body" in note_types
    include_visit_next = note_types is None or "visit_note_next_action" in note_types
    visit_notes = _scoped_visit_notes(
        source_id=source_id,
        visible_batch=visible_batch,
        include_history=include_history,
    )
    if date_from:
        visit_notes = visit_notes.filter(visited_on__gte=date_from)
    if date_to:
        visit_notes = visit_notes.filter(visited_on__lte=date_to)
    visit_notes = visit_notes.order_by("-updated_at", "-id")
    for note in visit_notes:
        household_name = note.household_name_snapshot or note.household_uid
        person_name = note.person_name_snapshot
        if include_visit_body and (note.body or "").strip():
            entries.append(
                _build_entry(
                    content_type_id=visit_note_type.id,
                    object_id=note.id,
                    field_name="body",
                    note_type="visit_note_body",
                    note_label=NOTE_TYPE_DEFINITIONS["visit_note_body"]["label"],
                    title=note.title or household_name,
                    text=note.body,
                    updated_at=note.updated_at,
                    household_id=note.household_uid,
                    household_name=household_name,
                    person_id=note.person_uid,
                    person_name=person_name,
                    schedule_id="",
                    legacy_source_id=note.legacy_source_id,
                    legacy_household_id=note.household_uid,
                    legacy_person_id=note.person_uid,
                    legacy_schedule_id="",
                    action_url=reverse("office:household_browser")
                    + f"?household_id={note.household_uid}",
                    action_label="この家を開く",
                    event_date=_date_to_text(note.visited_on),
                    batch_snapshot_id=(
                        note.related_batch.prepared_snapshot_id if note.related_batch_id else ""
                    ),
                    assignment_map=assignment_map,
                )
            )
        if include_visit_next and (note.next_action or "").strip():
            entries.append(
                _build_entry(
                    content_type_id=visit_note_type.id,
                    object_id=note.id,
                    field_name="next_action",
                    note_type="visit_note_next_action",
                    note_label=NOTE_TYPE_DEFINITIONS["visit_note_next_action"]["label"],
                    title=note.title or household_name,
                    text=note.next_action,
                    updated_at=note.updated_at,
                    household_id=note.household_uid,
                    household_name=household_name,
                    person_id=note.person_uid,
                    person_name=person_name,
                    schedule_id="",
                    legacy_source_id=note.legacy_source_id,
                    legacy_household_id=note.household_uid,
                    legacy_person_id=note.person_uid,
                    legacy_schedule_id="",
                    action_url=reverse("office:household_browser")
                    + f"?household_id={note.household_uid}",
                    action_label="この家を開く",
                    event_date=_date_to_text(note.visited_on),
                    batch_snapshot_id=(
                        note.related_batch.prepared_snapshot_id if note.related_batch_id else ""
                    ),
                    assignment_map=assignment_map,
                )
            )

    postal_type = content_types[PostalReviewResolution]
    include_postal_note = note_types is None or "postal_review_note" in note_types
    for row in PostalReviewResolution.objects.filter(source__source_id=source_id).order_by("-updated_at", "-id"):
        if not include_postal_note:
            break
        if not (row.note or "").strip():
            continue
        entries.append(
            _build_entry(
                content_type_id=postal_type.id,
                object_id=row.id,
                field_name="note",
                note_type="postal_review_note",
                note_label=NOTE_TYPE_DEFINITIONS["postal_review_note"]["label"],
                title=row.entry_head_name or row.target_household_name_snapshot or "郵送照合",
                text=row.note,
                updated_at=row.updated_at,
                household_id=row.selected_household_uid,
                household_name=row.target_household_name_snapshot or row.entry_head_name,
                person_id="",
                person_name="",
                schedule_id="",
                legacy_source_id=row.source.source_id,
                legacy_household_id=row.selected_household_uid,
                legacy_person_id="",
                legacy_schedule_id="",
                action_url=reverse("office:postal_review"),
                action_label="郵送照合を開く",
                batch_snapshot_id="",
                assignment_map=assignment_map,
            )
        )

    hand_type = content_types[HandDeliveryReviewResolution]
    include_hand_note = note_types is None or "hand_delivery_review_note" in note_types
    for row in HandDeliveryReviewResolution.objects.filter(source__source_id=source_id).order_by("-updated_at", "-id"):
        if not include_hand_note:
            break
        if not (row.note or "").strip():
            continue
        entries.append(
            _build_entry(
                content_type_id=hand_type.id,
                object_id=row.id,
                field_name="note",
                note_type="hand_delivery_review_note",
                note_label=NOTE_TYPE_DEFINITIONS["hand_delivery_review_note"]["label"],
                title=row.entry_head_name or row.target_household_name_snapshot or "手配り照合",
                text=row.note,
                updated_at=row.updated_at,
                household_id=row.selected_household_uid,
                household_name=row.target_household_name_snapshot or row.entry_head_name,
                person_id="",
                person_name="",
                schedule_id="",
                legacy_source_id=row.source.source_id,
                legacy_household_id=row.selected_household_uid,
                legacy_person_id="",
                legacy_schedule_id="",
                action_url=reverse("office:hand_delivery_review"),
                action_label="手配り照合を開く",
                batch_snapshot_id="",
                assignment_map=assignment_map,
            )
        )

    district_type = content_types[DistrictMemberSheetState]
    include_district_note = note_types is None or "district_member_sheet_note" in note_types
    for state in DistrictMemberSheetState.objects.select_related("district", "source").filter(
        source__source_id=source_id
    ).order_by("-updated_at", "-id"):
        if not include_district_note:
            break
        if not (state.manual_note or "").strip():
            continue
        entries.append(
            _build_entry(
                content_type_id=district_type.id,
                object_id=state.id,
                field_name="manual_note",
                note_type="district_member_sheet_note",
                note_label=NOTE_TYPE_DEFINITIONS["district_member_sheet_note"]["label"],
                title=state.district.name,
                text=state.manual_note,
                updated_at=state.updated_at,
                household_id="",
                household_name=state.district.name,
                person_id="",
                person_name="",
                schedule_id="",
                legacy_source_id=state.source.source_id,
                legacy_household_id="",
                legacy_person_id="",
                legacy_schedule_id="",
                action_url=reverse("office:district_member_sheets"),
                action_label="地区メモを開く",
                batch_snapshot_id="",
                assignment_map=assignment_map,
            )
        )
    entries.sort(key=lambda item: item["sort_key"], reverse=True)
    return entries


def _memo_entry_count(
    *,
    source_id: str,
    visible_batch: ImportBatch | None,
    include_history: bool,
) -> int:
    return sum(
        [
            _scoped_households(
                source_id=source_id,
                visible_batch=visible_batch,
                include_history=include_history,
            ).exclude(notes__exact="").count(),
            _scoped_people(
                source_id=source_id,
                visible_batch=visible_batch,
                include_history=include_history,
            ).exclude(person_note__exact="").count(),
            _scoped_people(
                source_id=source_id,
                visible_batch=visible_batch,
                include_history=include_history,
            ).exclude(deceased_note__exact="").count(),
            _scoped_service_schedules(
                source_id=source_id,
                visible_batch=visible_batch,
                include_history=include_history,
            ).exclude(notes__exact="").count(),
            _scoped_visit_notes(
                source_id=source_id,
                visible_batch=visible_batch,
                include_history=include_history,
            ).exclude(body__exact="").count(),
            _scoped_visit_notes(
                source_id=source_id,
                visible_batch=visible_batch,
                include_history=include_history,
            ).exclude(next_action__exact="").count(),
            PostalReviewResolution.objects.filter(source__source_id=source_id).exclude(note__exact="").count(),
            HandDeliveryReviewResolution.objects.filter(source__source_id=source_id).exclude(note__exact="").count(),
            DistrictMemberSheetState.objects.filter(source__source_id=source_id).exclude(manual_note__exact="").count(),
        ]
    )


__all__ = ["_memo_entries", "_memo_entry_count"]
