from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.imports import auxiliary_hand_delivery as hand_delivery_tools
from apps.imports import auxiliary_postal as postal_tools
from apps.imports.models import HandDeliveryReviewResolution, LegacySource
from apps.office import services
from apps.office.views.common import _ensure_source_record
from apps.office.views.settings_auxiliary_shared import _with_optional_query
from apps.office.web_support import _request_actor_label


@require_POST
def import_hand_delivery_districts(request: HttpRequest) -> HttpResponse:
    hand_delivery_folder = request.POST.get("hand_delivery_folder") or ""
    active_source_id = _ensure_source_record(None).source_id
    try:
        result = hand_delivery_tools.import_hand_delivery_district_assignments(
            active_source_id,
            folder_name=hand_delivery_folder or None,
            editor_label=_request_actor_label(request),
            change_note=request.POST.get("change_note", ""),
        )
    except (FileNotFoundError, LegacySource.DoesNotExist, ValueError) as exc:
        messages.error(request, f"手配りCSV取込に失敗しました: {exc}")
        return redirect(
            _with_optional_query(
                reverse("office:settings_home"),
                hand_delivery_folder=hand_delivery_folder,
            )
        )

    summary = (
        f"地区 {result['created_districts']}件作成 / "
        f"戸主 {result['assigned_households']}件割当 / "
        f"地区役員 {result['officer_updates']}件更新"
    )
    if result["contact_updates"]:
        summary += f" / 住所等更新 {result['contact_updates']}件"
    if result["updated_districts"]:
        summary += f" / 地区更新 {result['updated_districts']}件"
    if result["skipped_rows"]:
        summary += f" / スキップ {result['skipped_rows']}行"
    messages.success(request, f"手配りCSVを反映しました: {summary}")
    if result["unmatched_count"]:
        messages.warning(
            request,
            "戸主と一致しなかった行があります: " + "、".join(result["unmatched_names"]),
        )
    if result["ambiguous_count"]:
        messages.warning(
            request,
            "同名で一意に決められなかった行があります: " + "、".join(result["ambiguous_names"]),
        )
    return redirect(
        _with_optional_query(
            reverse("office:settings_home"),
            hand_delivery_folder=result["selected_folder_name"],
        )
    )


def hand_delivery_review(request: HttpRequest) -> HttpResponse:
    hand_delivery_folder = request.GET.get("hand_delivery_folder") or ""
    active_source_id = services.operational_source_id()
    analysis = hand_delivery_tools.analyze_hand_delivery_district_rows(
        active_source_id,
        folder_name=hand_delivery_folder or None,
    )
    resolve_row = (request.GET.get("resolve_row") or "").strip()
    resolve_query = (request.GET.get("resolve_query") or "").strip()
    selected_review_row = None
    replacement_candidates: list[dict] = []
    if resolve_row.isdigit():
        row_number = int(resolve_row)
        selected_review_row = next(
            (
                item
                for item in [*analysis["review_rows"], *analysis["matched_rows"]]
                if item["row_number"] == row_number
            ),
            None,
        )
        if selected_review_row is not None and resolve_query:
            replacement_candidates = postal_tools.search_households_for_postal_review(
                active_source_id,
                resolve_query,
            )
    context = {
        "selected_source_id": active_source_id,
        "analysis": analysis,
        "resolve_row": resolve_row,
        "resolve_query": resolve_query,
        "selected_review_row": selected_review_row,
        "replacement_candidates": replacement_candidates,
    }
    return render(request, "office/hand_delivery_review.html", context)


def _record_hand_delivery_review_resolution(
    *,
    source: LegacySource,
    folder_name: str,
    row_number: int,
    resolution_kind: str,
    selected_household_uid: str,
    entry_head_name: str,
    target_household_name_snapshot: str,
    editor_label: str,
    note: str,
) -> None:
    HandDeliveryReviewResolution.objects.update_or_create(
        source=source,
        folder_name=folder_name,
        row_number=row_number,
        defaults={
            "resolution_kind": resolution_kind,
            "selected_household_uid": selected_household_uid,
            "entry_head_name": entry_head_name,
            "target_household_name_snapshot": target_household_name_snapshot,
            "editor_label": editor_label,
            "note": note,
        },
    )


def _find_hand_delivery_review_entry(analysis: dict, row_number: int) -> dict | None:
    return next(
        (
            item
            for item in [
                *analysis.get("review_rows", []),
                *analysis.get("matched_rows", []),
                *analysis.get("ambiguous_rows", []),
            ]
            if item.get("row_number") == row_number
        ),
        None,
    )
