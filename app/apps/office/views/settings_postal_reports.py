from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.core.services import tenant_policy
from apps.imports import auxiliary_postal as postal_tools
from apps.office import services
from apps.office.services.label_pdf import (
    render_address_label_pdf,
    render_delivery_label_pdf,
    render_monto_sodai_label_pdf,
)


def _requests_pdf_response(request: HttpRequest) -> bool:
    return (request.GET.get("format") or "").strip().lower() == "pdf"


def _request_checkbox_enabled(request: HttpRequest, name: str) -> bool:
    return (request.GET.get(name) or "").strip().lower() in {"1", "true", "on", "yes"}


def _inline_pdf_response(*, pdf_bytes: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def _apply_marker_text(label_context: dict, *, marker_text: str) -> dict:
    if not label_context.get("available"):
        return label_context
    updated_pages = []
    for page in label_context.get("label_pages", []):
        updated_page = []
        for label in page:
            if not label:
                updated_page.append(label)
                continue
            updated_page.append({**label, "marker_text": marker_text})
        updated_pages.append(updated_page)
    return {
        **label_context,
        "label_pages": updated_pages,
    }


def postal_compare(request: HttpRequest) -> HttpResponse:
    postal_folder = request.GET.get("postal_folder") or ""
    active_source_id = services.operational_source_id()
    analysis = postal_tools.build_postal_compare_context(
        active_source_id,
        folder_name=postal_folder or None,
    )
    context = {
        "selected_source_id": active_source_id,
        "analysis": analysis,
    }
    return render(request, "office/postal_compare.html", context)


def postal_labels(request: HttpRequest) -> HttpResponse:
    active_source_id = services.operational_source_id()
    selected_household_uids = tuple(
        dict.fromkeys(
            value
            for raw_value in request.GET.getlist("household_uid")
            if (value := raw_value.strip())
        )
    )
    include_memorial_notice_marker = _request_checkbox_enabled(
        request,
        "include_memorial_notice_marker",
    )
    label_context = services.build_postal_label_context(
        active_source_id,
        include_memorial_notice_marker=include_memorial_notice_marker,
        household_uids=selected_household_uids or None,
    )
    if _requests_pdf_response(request) and label_context.get("available"):
        return _inline_pdf_response(
            pdf_bytes=render_address_label_pdf(
                label_pages=label_context["label_pages"],
                title="郵送ラベル印刷",
            ),
            filename="postal-labels.pdf",
        )
    context = {
        "selected_source_id": active_source_id,
        "include_memorial_notice_marker": include_memorial_notice_marker,
        "marker_labels": tenant_policy.marker_labels(),
        **label_context,
    }
    return render(request, "office/postal_labels.html", context)


def district_officer_postal_labels(request: HttpRequest) -> HttpResponse:
    active_source_id = services.operational_source_id()
    role_document_labels = tenant_policy.role_document_labels()
    label_context = services.build_district_officer_postal_label_context(active_source_id)
    if _requests_pdf_response(request) and label_context.get("available"):
        return _inline_pdf_response(
            pdf_bytes=render_address_label_pdf(
                label_pages=label_context["label_pages"],
                title=f"{role_document_labels['district_officer_postal_labels']}印刷",
            ),
            filename="district-officer-postal-labels.pdf",
        )
    context = {
        "selected_source_id": active_source_id,
        **label_context,
    }
    return render(request, "office/district_officer_postal_labels.html", context)


def monto_sodai_postal_labels(request: HttpRequest) -> HttpResponse:
    active_source_id = services.operational_source_id()
    omit_role_title = _request_checkbox_enabled(request, "omit_role_title")
    role_labels = tenant_policy.role_labels()
    role_document_labels = tenant_policy.role_document_labels()
    label_context = services.build_monto_sodai_postal_label_context(
        active_source_id,
        include_role_title=not omit_role_title,
    )
    label_context = _apply_marker_text(
        label_context,
        marker_text="" if omit_role_title else role_labels["monto_sodai"],
    )
    if _requests_pdf_response(request) and label_context.get("available"):
        return _inline_pdf_response(
            pdf_bytes=render_monto_sodai_label_pdf(
                label_pages=label_context["label_pages"],
                title=f"{role_document_labels['monto_sodai_postal_labels']}印刷",
            ),
            filename="monto-sodai-postal-labels.pdf",
        )
    context = {
        "selected_source_id": active_source_id,
        "current_page": "monto_sodai_roster",
        "omit_role_title": omit_role_title,
        **label_context,
    }
    return render(request, "office/monto_sodai_postal_labels.html", context)


def district_officer_delivery_labels(request: HttpRequest) -> HttpResponse:
    active_source_id = services.operational_source_id()
    role_document_labels = tenant_policy.role_document_labels()
    label_context = services.build_district_officer_delivery_label_context(active_source_id)
    if _requests_pdf_response(request) and label_context.get("available"):
        return _inline_pdf_response(
            pdf_bytes=render_delivery_label_pdf(
                label_pages=label_context["label_pages"],
                title=f"{role_document_labels['district_officer_delivery_labels']}印刷",
            ),
            filename="district-officer-delivery-labels.pdf",
        )
    context = {
        "selected_source_id": active_source_id,
        **label_context,
    }
    return render(request, "office/district_officer_delivery_labels.html", context)


__all__ = [
    "district_officer_delivery_labels",
    "district_officer_postal_labels",
    "monto_sodai_postal_labels",
    "postal_compare",
    "postal_labels",
]
