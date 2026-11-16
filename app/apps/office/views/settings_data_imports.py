from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.imports import auxiliary_hand_delivery as hand_delivery_tools
from apps.imports import auxiliary_postal as postal_tools
from apps.office import services


def _selected_auxiliary_folder(request: HttpRequest, key: str, candidates: list[dict]) -> str:
    selected_folder = (request.GET.get(key) or "").strip()
    if selected_folder:
        return selected_folder
    if candidates:
        return str(candidates[0]["folder_name"])
    return ""


def data_imports(request: HttpRequest) -> HttpResponse:
    active_source_id = services.operational_source_id()
    operational_source_status = services.operational_source_status()
    operational_latest_export = services.latest_export_snapshot(active_source_id)

    hand_delivery_candidates = (
        hand_delivery_tools.list_auxiliary_hand_delivery_csv_candidates()
    )
    hand_delivery_folder = _selected_auxiliary_folder(
        request,
        "hand_delivery_folder",
        hand_delivery_candidates,
    )
    hand_delivery_csv_path = hand_delivery_tools.latest_auxiliary_hand_delivery_csv_path(
        hand_delivery_folder or None
    )

    postal_candidates = postal_tools.list_auxiliary_postal_csv_candidates()
    postal_folder = _selected_auxiliary_folder(request, "postal_folder", postal_candidates)
    postal_csv_path = postal_tools.latest_auxiliary_postal_csv_path(postal_folder or None)

    context = {
        "current_page": "data_imports",
        "selected_source_id": active_source_id,
        "operational_source_status": operational_source_status,
        "operational_latest_export": operational_latest_export,
        "hand_delivery_folder": hand_delivery_folder,
        "hand_delivery_candidates": hand_delivery_candidates,
        "hand_delivery_csv_path": str(hand_delivery_csv_path) if hand_delivery_csv_path else "",
        "postal_folder": postal_folder,
        "postal_candidates": postal_candidates,
        "postal_csv_path": str(postal_csv_path) if postal_csv_path else "",
    }
    return render(request, "office/data_imports.html", context)


__all__ = ["data_imports"]
