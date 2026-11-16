from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.imports import auxiliary_hand_delivery as hand_delivery_tools
from apps.imports import canonical_population
from apps.imports.models import Household
from apps.office.services.auxiliary_head_replacement import replace_review_household_head
from apps.office.views.common import _ensure_source_record
from apps.office.views.settings_auxiliary_shared import (
    _flash_record_action_message,
    _with_optional_query,
)
from apps.office.views.settings_hand_delivery_review_views import (
    _find_hand_delivery_review_entry,
)
from apps.office.web_support import _normalize_time_machine_mode, _request_actor_label


@require_POST
def replace_hand_delivery_household_head(request: HttpRequest) -> HttpResponse:
    hand_delivery_folder = request.POST.get("hand_delivery_folder") or ""
    row_number_text = (request.POST.get("row_number") or "").strip()
    legacy_household_id = (request.POST.get("household_id") or "").strip()
    editor_label = _request_actor_label(request)
    keep_old_head_current = _normalize_time_machine_mode(
        request.POST.get("keep_old_head_current")
    )
    source_record = _ensure_source_record(None)
    active_source_id = source_record.source_id
    redirect_url = _with_optional_query(
        reverse("office:hand_delivery_review"),
        hand_delivery_folder=hand_delivery_folder,
    )

    if not row_number_text.isdigit() or not legacy_household_id:
        messages.error(request, "差し替え対象の手配り行または戸主が不正です。")
        return redirect(redirect_url)

    analysis = hand_delivery_tools.analyze_hand_delivery_district_rows(
        active_source_id,
        folder_name=hand_delivery_folder or None,
    )
    row_number = int(row_number_text)
    entry = _find_hand_delivery_review_entry(analysis, row_number)
    if entry is None:
        messages.error(request, "対象の手配り行が見つかりません。先に照合結果を更新してください。")
        return redirect(redirect_url)
    selected_folder_name = analysis["selected_folder_name"]

    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    if provenance_batch is None:
        messages.error(request, "現行台帳が見つかりません。")
        return redirect(redirect_url)

    household = get_object_or_404(
        Household.objects.select_related("head_person"),
        household_uid=legacy_household_id,
        deleted_at__isnull=True,
    )

    result = replace_review_household_head(
        source=source_record,
        household=household,
        entry=entry,
        folder_name=selected_folder_name,
        row_number=row_number,
        review_kind="hand_delivery",
        editor_label=editor_label,
        keep_old_head_current=keep_old_head_current,
    )
    replacement_person = result.replacement_person
    person_log = result.person_log
    old_head_log = result.old_head_log
    household_log = result.household_log

    if person_log is not None:
        _flash_record_action_message(
            request,
            person_log,
            f"{replacement_person.name} を戸主 person として設定しました。",
        )
    if old_head_log is not None:
        _flash_record_action_message(
            request,
            old_head_log,
            (
                "旧戸主 current person を現在帳へ残しました。"
                if keep_old_head_current
                else "旧戸主 current person を退避しました。必要なら履歴から復元できます。"
            ),
        )
    _flash_record_action_message(
        request,
        household_log,
        f"台帳ID {household.household_uid} の戸主を {replacement_person.name} に差し替えました。",
    )
    return redirect(redirect_url)
