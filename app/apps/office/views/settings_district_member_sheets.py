from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.services import tenant_policy
from apps.imports.models import DistrictMemberSheetState, LegacySource
from apps.office import services
from apps.office.services.district_history import (
    record_district_member_sheet_change,
    serialize_district_member_sheet,
)
from apps.office.views.common import _ensure_source_record
from apps.office.web_support import _request_actor_label


def _request_checkbox_enabled(request: HttpRequest, name: str) -> bool:
    return (request.GET.get(name) or request.POST.get(name) or "").strip().lower() in {
        "1",
        "true",
        "on",
        "yes",
    }


def _district_member_sheet_url(*, include_memorial_notice_marker: bool = False) -> str:
    url = reverse("office:district_member_sheets")
    if include_memorial_notice_marker:
        return f"{url}?include_memorial_notice_marker=1"
    return url


def _district_member_sheet_print_url(*, include_memorial_notice_marker: bool = False) -> str:
    url = reverse("office:district_member_sheets_print")
    if include_memorial_notice_marker:
        return f"{url}?include_memorial_notice_marker=1"
    return url


def _persist_district_member_sheet_states(
    *,
    source_record: LegacySource,
    sheet_context: dict,
    manual_notes_by_district: dict[int, str] | None = None,
    mark_printed: bool = False,
    editor_label: str = "system",
    change_note: str = "",
) -> None:
    now = timezone.now()
    with transaction.atomic():
        for sheet in sheet_context["sheets"]:
            district_id = int(sheet["district_id"])
            if manual_notes_by_district is None:
                manual_note = (sheet.get("manual_note") or "").rstrip()
            else:
                manual_note = manual_notes_by_district.get(district_id, "").rstrip()
            state = DistrictMemberSheetState.objects.select_related("source", "district").filter(
                source=source_record,
                district_id=district_id,
            ).first()
            before_state = serialize_district_member_sheet(state) if state is not None else {}

            if mark_printed:
                defaults = {
                    "manual_note": manual_note,
                    "last_printed_member_snapshot": sheet["member_snapshot"],
                    "last_printed_prepared_snapshot_id": sheet_context["prepared_snapshot_id"],
                    "last_printed_at": now,
                }
                if state is None:
                    state = DistrictMemberSheetState.objects.create(
                        source=source_record,
                        district_id=district_id,
                        **defaults,
                    )
                else:
                    for field_name, value in defaults.items():
                        setattr(state, field_name, value)
                    state.save(
                        update_fields=[
                            "manual_note",
                            "last_printed_member_snapshot",
                            "last_printed_prepared_snapshot_id",
                            "last_printed_at",
                            "updated_at",
                        ]
                    )
                record_district_member_sheet_change(
                    state,
                    before_data=before_state,
                    editor_label=editor_label,
                    change_note=change_note or "地区メンバー一覧の今回印刷を記録",
                )
                continue

            if state is None:
                if not manual_note:
                    continue
                state = DistrictMemberSheetState.objects.create(
                    source=source_record,
                    district_id=district_id,
                    manual_note=manual_note,
                )
                record_district_member_sheet_change(
                    state,
                    before_data=before_state,
                    editor_label=editor_label,
                    change_note=change_note or "地区メンバー一覧のメモを保存",
                )
                continue

            if state.manual_note != manual_note:
                state.manual_note = manual_note
                state.save(update_fields=["manual_note", "updated_at"])
                record_district_member_sheet_change(
                    state,
                    before_data=before_state,
                    editor_label=editor_label,
                    change_note=change_note or "地区メンバー一覧のメモを保存",
                )


def district_member_sheets(request: HttpRequest) -> HttpResponse:
    source_record = _ensure_source_record(None)
    active_source_id = source_record.source_id
    include_memorial_notice_marker = _request_checkbox_enabled(
        request,
        "include_memorial_notice_marker",
    )

    if request.method == "POST":
        sheet_context = services.build_district_member_sheet_context(
            active_source_id,
            include_memorial_notice_marker=include_memorial_notice_marker,
        )
        action = (request.POST.get("action") or "save_notes").strip()
        manual_notes_by_district = {
            int(sheet["district_id"]): (request.POST.get(f"manual_note_{sheet['district_id']}") or "")
            for sheet in sheet_context["sheets"]
        }
        _persist_district_member_sheet_states(
            source_record=source_record,
            sheet_context=sheet_context,
            manual_notes_by_district=manual_notes_by_district,
            editor_label=_request_actor_label(request),
        )

        if action == "save_and_preview":
            messages.success(request, "メモを保存しました。印刷イメージへ移動します。")
            return redirect(
                _district_member_sheet_print_url(
                    include_memorial_notice_marker=include_memorial_notice_marker
                )
            )

        messages.success(request, "地区メンバー一覧のメモを保存しました。")
        return redirect(
            _district_member_sheet_url(
                include_memorial_notice_marker=include_memorial_notice_marker
            )
        )

    sheet_context = services.build_district_member_sheet_context(
        active_source_id,
        include_memorial_notice_marker=include_memorial_notice_marker,
    )
    context = {
        "selected_source_id": active_source_id,
        "current_page": "district_member_sheets",
        "include_memorial_notice_marker": include_memorial_notice_marker,
        "marker_labels": tenant_policy.marker_labels(),
        **sheet_context,
    }
    return render(request, "office/district_member_sheets.html", context)


def district_member_sheets_print(request: HttpRequest) -> HttpResponse:
    source_record = _ensure_source_record(None)
    active_source_id = source_record.source_id
    include_memorial_notice_marker = _request_checkbox_enabled(
        request,
        "include_memorial_notice_marker",
    )
    sheet_context = services.build_district_member_sheet_context(
        active_source_id,
        include_memorial_notice_marker=include_memorial_notice_marker,
    )

    if request.method == "POST":
        if (request.POST.get("action") or "").strip() == "mark_printed":
            _persist_district_member_sheet_states(
                source_record=source_record,
                sheet_context=sheet_context,
                mark_printed=True,
                editor_label=_request_actor_label(request),
            )
            messages.success(request, "今回の地区メンバー一覧を前回印刷として記録しました。")
        return redirect(
            _district_member_sheet_print_url(
                include_memorial_notice_marker=include_memorial_notice_marker
            )
        )

    context = {
        "selected_source_id": active_source_id,
        "current_page": "district_member_sheets",
        "include_memorial_notice_marker": include_memorial_notice_marker,
        "marker_labels": tenant_policy.marker_labels(),
        **sheet_context,
    }
    return render(request, "office/district_member_sheets_print.html", context)


__all__ = [
    "_persist_district_member_sheet_states",
    "district_member_sheets",
    "district_member_sheets_print",
]
