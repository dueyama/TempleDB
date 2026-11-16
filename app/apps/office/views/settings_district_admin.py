from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.imports import canonical_population
from apps.imports.forms import DistrictForm
from apps.imports.models import (
    FAMILY_CATEGORY_CURRENT,
    HOUSEHOLD_DELIVERY_DISTRICT,
    District,
    Household,
    HouseholdProfile,
    ImportBatch,
    Person,
)
from apps.office import services
from apps.office.services.district_history import record_district_change, serialize_district
from apps.office.services.district_ops import (
    _assign_district_officer_to_person,
    _clear_district_officer_for_district,
    _district_officer_choices,
    _district_officer_person_for_district,
)
from apps.office.web_support import _districts_url, _normalized_request_url, _request_actor_label


def _district_officer_key(source_id: str, person: Person | None) -> str:
    if person is None:
        return ""
    return f"{source_id}:{person.household.household_uid}:{person.person_uid}"


def _resolve_district_officer_person_from_key(
    source_id: str,
    officer_key: str,
    *,
    batch: ImportBatch | None,
) -> Person | None:
    del batch
    canonical_population.canonical_provenance_import_batch(source_id=source_id)
    resolved_key = (officer_key or "").strip()
    if not resolved_key:
        return None
    source_key, separator, remainder = resolved_key.partition(":")
    household_id, separator2, person_id = remainder.partition(":")
    if (
        not separator
        or not separator2
        or source_key != source_id
        or not household_id.strip()
        or not person_id.strip()
    ):
        return None
    return (
        Person.objects.select_related("household")
        .filter(
            deleted_at__isnull=True,
            family_category=FAMILY_CATEGORY_CURRENT,
            household__household_uid=household_id.strip(),
            person_uid=person_id.strip(),
        )
        .first()
    )


def _decorate_districts_with_person_officers(
    source_id: str,
    districts: list[District],
    *,
    batch: ImportBatch | None,
) -> list[District]:
    officers_by_district = services.district_officer_people_by_district(source_id, batch=batch)
    for district in districts:
        officer_entries = officers_by_district.get(district.id, [])
        if len(officer_entries) == 1:
            officer_person, _profile = officer_entries[0]
            district.current_officer_name = (
                officer_person.name or officer_person.person_uid
            ).strip()
            district.current_officer_source_id = source_id
            district.current_officer_household_id = officer_person.household.household_uid
            district.current_officer_person_id = officer_person.person_uid
            continue
        if len(officer_entries) > 1:
            district.current_officer_name = " / ".join(
                (person.name or person.person_uid).strip() or person.person_uid
                for person, _profile in officer_entries
            )
            district.current_officer_source_id = source_id
            district.current_officer_household_id = ""
            district.current_officer_person_id = ""
            continue
        district.current_officer_name = ""
        district.current_officer_source_id = ""
        district.current_officer_household_id = ""
        district.current_officer_person_id = ""
    return districts


def _decorate_districts_with_household_counts(
    source_id: str,
    districts: list[District],
    *,
    batch: ImportBatch | None,
) -> list[District]:
    district_ids = [district.id for district in districts]
    if not district_ids:
        for district in districts:
            district.member_household_count = 0
        return districts

    del batch
    canonical_population.canonical_provenance_import_batch(source_id=source_id)
    household_ids = Household.objects.filter(
        deleted_at__isnull=True,
    ).values_list("household_uid", flat=True)
    counts_by_district = {
        row["district_id"]: row["count"]
        for row in HouseholdProfile.objects.filter(
            source__source_id=source_id,
            delivery_method=HOUSEHOLD_DELIVERY_DISTRICT,
            district_id__in=district_ids,
            household_uid__in=household_ids,
        )
        .values("district_id")
        .annotate(count=Count("id"))
    }
    for district in districts:
        district.member_household_count = counts_by_district.get(district.id, 0)
    return districts


def districts(request: HttpRequest) -> HttpResponse:
    active_source_id = services.operational_source_id()
    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    editing_id = request.GET.get("edit") or request.POST.get("district_id") or ""
    editing_district = None
    if editing_id:
        editing_district = get_object_or_404(District, pk=editing_id)
    officer_choices = _district_officer_choices(active_source_id, editing_district)
    current_officer = (
        _district_officer_person_for_district(active_source_id, editing_district)
        if editing_district is not None
        else None
    )
    initial_officer_key = _district_officer_key(active_source_id, current_officer)

    if request.method == "POST":
        action = request.POST.get("action") or "save"
        if action == "toggle_active":
            district = get_object_or_404(District, pk=request.POST.get("district_id"))
            before_district = serialize_district(district)
            with transaction.atomic():
                district.is_active = not district.is_active
                district.save(update_fields=["is_active", "updated_at"])
                record_district_change(
                    district,
                    source_id=active_source_id,
                    before_data=before_district,
                    editor_label=_request_actor_label(request),
                    change_note="地区設定から有効・停止を変更",
                )
            messages.success(
                request,
                f"地区 {district.name} を{'有効' if district.is_active else '停止'}にしました。",
            )
            return redirect(_districts_url())

        before_district = serialize_district(editing_district) if editing_district is not None else {}
        form = DistrictForm(
            request.POST,
            instance=editing_district,
            officer_choices=officer_choices,
            initial_officer_key=initial_officer_key,
        )
        if form.is_valid():
            selected_officer = _resolve_district_officer_person_from_key(
                active_source_id,
                form.cleaned_data.get("officer_person_key") or "",
                batch=provenance_batch,
            )
            selected_key = (form.cleaned_data.get("officer_person_key") or "").strip()
            if selected_key and selected_officer is None:
                form.add_error("officer_person_key", "地区役員候補が現行台帳に見つかりません。")
            else:
                with transaction.atomic():
                    district = form.save()
                    record_district_change(
                        district,
                        source_id=active_source_id,
                        before_data=before_district,
                        editor_label=_request_actor_label(request),
                        change_note="地区設定から地区情報を保存",
                    )
                    if selected_officer is not None:
                        _assign_district_officer_to_person(
                            district, selected_officer,
                            editor_label=_request_actor_label(request),
                            change_note="地区設定から地区役員を保存",
                        )
                    else:
                        _clear_district_officer_for_district(
                            active_source_id, district,
                            editor_label=_request_actor_label(request),
                            change_note="地区設定から地区役員を解除",
                        )
                messages.success(request, f"地区 {district.name} を保存しました。")
                return redirect(_districts_url())
    else:
        form = DistrictForm(
            instance=editing_district,
            officer_choices=officer_choices,
            initial_officer_key=initial_officer_key,
        )

    districts = _decorate_districts_with_person_officers(
        active_source_id,
        list(District.objects.all()),
        batch=provenance_batch,
    )
    districts = _decorate_districts_with_household_counts(
        active_source_id,
        districts,
        batch=provenance_batch,
    )
    context = {
        "selected_source_id": active_source_id,
        "districts": districts,
        "active_districts": [district for district in districts if district.is_active],
        "inactive_districts": [district for district in districts if not district.is_active],
        "form": form,
        "editing_district": editing_district,
        "current_url": _normalized_request_url(request),
        "officer_choice_count": len(officer_choices),
        "latest_district_household_batch": (
            provenance_batch.prepared_snapshot_id if provenance_batch else ""
        ),
    }
    return render(request, "office/districts.html", context)


__all__ = [
    "_decorate_districts_with_household_counts",
    "_decorate_districts_with_person_officers",
    "_district_officer_key",
    "_resolve_district_officer_person_from_key",
    "districts",
]
