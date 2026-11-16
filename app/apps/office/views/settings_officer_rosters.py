from __future__ import annotations

import csv
from io import StringIO

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST, require_safe

from apps.core.services import tenant_policy
from apps.imports.models import Person, RecordEditLog
from apps.office import services
from apps.office.services.record_history_mutations import _create_record_edit_log
from apps.office.services.record_history_snapshot import (
    _serialize_person_record,
)
from apps.office.views.common import _canonical_ledger_context
from apps.office.views.settings_auxiliary_shared import (
    _flash_record_action_message,
)
from apps.office.web_support import _normalized_request_url, _request_actor_label

ROLE_REMOVAL_SPECS = {
    "district_officer": {
        "field_name": "is_district_officer",
        "document_label_key": "district_officer_roster",
        "role_label_key": "district_officer",
    },
    "responsible_officer": {
        "field_name": "is_responsible_officer",
        "document_label_key": "responsible_officer_roster",
        "role_label_key": "responsible_officer",
    },
    "monto_sodai": {
        "field_name": "is_monto_sodai",
        "document_label_key": "monto_sodai_roster",
        "role_label_key": "monto_sodai_formal",
    },
}


def _role_removal_messages(*, role_key: str, person_label: str) -> dict[str, str] | None:
    spec = ROLE_REMOVAL_SPECS.get(role_key)
    if spec is None:
        return None
    role_labels = tenant_policy.role_labels()
    role_document_labels = tenant_policy.role_document_labels()
    role_label = role_labels[spec["role_label_key"]]
    document_label = role_document_labels[spec["document_label_key"]]
    return {
        "field_name": spec["field_name"],
        "change_note": f"{document_label}から{role_label}を解除",
        "success_message": f"{person_label} から{role_label}を外しました。",
    }


def district_officer_roster(request: HttpRequest) -> HttpResponse:
    active_source_id = services.operational_source_id()
    roster_context = services.build_district_officer_roster_context(active_source_id)
    if (request.GET.get("format") or "").strip().lower() == "csv":
        return _officer_roster_csv_response(roster_context, filename="district-officers.csv")
    role_labels = tenant_policy.role_labels()
    role_document_labels = tenant_policy.role_document_labels()
    context = {
        "selected_source_id": active_source_id,
        "current_page": "district_officer_roster",
        "title": role_document_labels["district_officer_roster"],
        "description": (
            f"{role_labels['district_officer']}フラグが付いている current person を一覧表示します。"
            "地区とのひも付けもここで確認できます。"
        ),
        "role_key": "district_officer",
        "remove_role_label": role_labels["district_officer"],
        "remove_action_url": reverse("office:remove_person_role"),
        "current_url": _normalized_request_url(request),
        "csv_export_url": reverse("office:district_officer_roster") + "?format=csv",
        **roster_context,
    }
    return render(request, "office/officer_roster.html", context)


def responsible_officer_roster(request: HttpRequest) -> HttpResponse:
    active_source_id = services.operational_source_id()
    roster_context = services.build_responsible_officer_roster_context(active_source_id)
    if (request.GET.get("format") or "").strip().lower() == "csv":
        return _officer_roster_csv_response(roster_context, filename="responsible-officers.csv")
    role_labels = tenant_policy.role_labels()
    role_document_labels = tenant_policy.role_document_labels()
    context = {
        "selected_source_id": active_source_id,
        "current_page": "responsible_officer_roster",
        "title": role_document_labels["responsible_officer_roster"],
        "description": (
            f"{role_labels['responsible_officer']}フラグが付いている current person を一覧表示します。"
        ),
        "role_key": "responsible_officer",
        "remove_role_label": role_labels["responsible_officer"],
        "remove_action_url": reverse("office:remove_person_role"),
        "current_url": _normalized_request_url(request),
        "csv_export_url": reverse("office:responsible_officer_roster") + "?format=csv",
        **roster_context,
    }
    return render(request, "office/officer_roster.html", context)


def _roster_csv_value(value: object) -> str:
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def _officer_roster_csv_response(roster_context: dict, *, filename: str) -> HttpResponse:
    if not roster_context.get("available"):
        return HttpResponse(
            roster_context.get("error_message") or "一覧対象の現行台帳がありません。",
            status=400,
            content_type="text/plain; charset=utf-8",
        )
    buffer = StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow(["氏名", "家名", "家ID", "個人ID", "役職", "担当地区", "所属地区", "所属地区の状態", "送付区分", "郵便番号", "住所", "電話"])
    for row in roster_context["rows"]:
        writer.writerow([_roster_csv_value(value) for value in (
            row.get("person_name", ""), row.get("household_name", ""),
            row.get("household_id", ""), row.get("person_id", ""),
            "、".join(row.get("role_badges", [])),
            "、".join(row.get("assigned_district_names", [])),
            row.get("home_district_name", ""),
            ("手配り停止中（郵送扱い）" if row.get("home_district_is_inactive") else "有効")
            if row.get("home_district_name") else "",
            row.get("delivery_method", ""),
            row.get("postal_code", ""), " ".join(row.get("address_lines", [])), row.get("phone", ""),
        )])
    response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def monto_sodai_roster(request: HttpRequest) -> HttpResponse:
    active_source_id = services.operational_source_id()
    roster_context = services.build_monto_sodai_roster_context(active_source_id)
    if (request.GET.get("format") or "").strip().lower() == "csv":
        return _officer_roster_csv_response(roster_context, filename="monto-sodai.csv")
    role_labels = tenant_policy.role_labels()
    role_document_labels = tenant_policy.role_document_labels()
    context = {
        "selected_source_id": active_source_id,
        "current_page": "monto_sodai_roster",
        "title": role_document_labels["monto_sodai_roster"],
        "description": (
            f"現在の{role_labels['monto_sodai_formal']}を一覧表示します。CSVに書き出せます。"
        ),
        "postal_label_url": reverse("office:monto_sodai_postal_labels"),
        "postal_label_label": role_document_labels["monto_sodai_postal_labels"],
        "role_key": "monto_sodai",
        "remove_role_label": role_labels["monto_sodai_formal"],
        "remove_action_url": reverse("office:remove_person_role"),
        "current_url": _normalized_request_url(request),
        "csv_export_url": reverse("office:monto_sodai_roster") + "?format=csv",
        **roster_context,
    }
    return render(request, "office/officer_roster.html", context)


@require_POST
def remove_person_role(request: HttpRequest) -> HttpResponse:
    _canonical_ledger_context()
    next_url = (request.POST.get("next") or "").strip() or reverse("office:settings_home")
    person_pk = (request.POST.get("person_pk") or "").strip()
    role_key = (request.POST.get("role_key") or "").strip()
    if not person_pk.isdigit():
        messages.error(request, "役職解除の対象 person が不正です。")
        return redirect(next_url)
    person = get_object_or_404(Person.objects.select_related("household"), pk=int(person_pk))

    before_data = _serialize_person_record(
        person, include_district_officer_context=role_key == "district_officer",
    )
    role_messages = _role_removal_messages(
        role_key=role_key,
        person_label=person.name or person.person_uid,
    )
    if role_messages is None:
        messages.error(request, "解除対象の役職が不正です。")
        return redirect(next_url)
    with transaction.atomic():
        setattr(person, role_messages["field_name"], False)
        person.save(update_fields=[role_messages["field_name"], "updated_at"])

        person = Person.objects.select_related("household", "deceased_profile").get(pk=person.pk)
        log_entry = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.PERSON,
            record=person,
            before_data=before_data,
            after_data=_serialize_person_record(
                person, include_district_officer_context=role_key == "district_officer",
            ),
            editor_label=_request_actor_label(request),
            change_note=role_messages["change_note"],
        )
    _flash_record_action_message(request, log_entry, role_messages["success_message"])
    return redirect(next_url)


__all__ = [
    "district_officer_roster",
    "monto_sodai_roster",
    "remove_person_role",
    "responsible_officer_roster",
]
