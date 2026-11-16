from __future__ import annotations

from urllib.parse import urlencode

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.imports.forms import GENDER_CHOICES
from apps.imports.models import Person, RecordEditLog
from apps.office.services.household_editing_core import _person_for_edit
from apps.office.services.record_history_mutations import (
    _create_record_edit_log,
    perform_record_delete_action,
)
from apps.office.services.record_history_snapshot import _serialize_person_record
from apps.office.views.common import _canonical_ledger_context
from apps.office.web_support import (
    _default_household_browser_url,
    _deleted_record_return_label,
    _request_actor_label,
    _resolve_next_url,
    _safe_deleted_record_return_url,
)

from .household_transition_shared import _flash_record_action_message


def update_person_gender_from_household_browser(
    request: HttpRequest,
    household_id: str,
    person_id: str,
) -> HttpResponse:
    _canonical_ledger_context()
    person = get_object_or_404(
        Person.objects.select_related("household", "deceased_profile"),
        household__household_uid=household_id,
        person_uid=person_id,
    )
    next_url = _resolve_next_url(
        request,
        _default_household_browser_url(household_id),
    )
    gender = (request.POST.get("gender") or "").strip() or "未決定"
    valid_genders = {choice[0] for choice in GENDER_CHOICES}
    if gender not in valid_genders:
        messages.warning(request, "性別の指定が不正です。")
        return redirect(next_url)
    change_note = (request.POST.get("change_note") or "").strip() or "戸主ブラウザで性別を更新"

    before_data = _serialize_person_record(person)
    with transaction.atomic():
        person.gender = gender
        person.save(update_fields=["gender", "updated_at"])
        person = _person_for_edit(person.pk)
        log_entry = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.PERSON,
            record=person,
            before_data=before_data,
            after_data=_serialize_person_record(person),
            editor_label=_request_actor_label(request),
            change_note=change_note,
        )
    _flash_record_action_message(
        request,
        log_entry,
        f"家族レコード {person.name or person.person_uid} の性別を {gender} に更新しました。",
    )
    return redirect(next_url)


def delete_person_from_same_name_candidates(
    request: HttpRequest,
    household_id: str,
    person_id: str,
) -> HttpResponse:
    _canonical_ledger_context()
    person = get_object_or_404(
        Person.objects.select_related("household", "deceased_profile"),
        household__household_uid=household_id,
        person_uid=person_id,
    )
    next_url = _resolve_next_url(
        request,
        reverse("office:data_quality"),
    )
    safe_return_url = _safe_deleted_record_return_url(
        next_url,
        household_id=household_id,
        deleted_record_type="person",
    )
    delete_result_mode = (request.GET.get("delete_result") or "").strip() in {"1", "true", "on"}

    if request.method == "POST":
        action = (request.POST.get("action") or "delete").strip()
        delete_outcome = perform_record_delete_action(
            action=action,
            record_type=RecordEditLog.RecordType.PERSON,
            record=person,
            serializer=_serialize_person_record,
            refresh=_person_for_edit,
            editor_label=_request_actor_label(request),
            change_note=(
                request.POST.get("change_note", "")
                or "同名候補一覧から家族レコードを削除"
            ),
            deleted_message=f"家族レコード {person.person_uid} を削除済みにしました。",
            restored_message=f"家族レコード {person.person_uid} を復元しました。",
        )
        if delete_outcome is not None:
            if action == "restore":
                messages.success(request, delete_outcome.user_message)
                return redirect(safe_return_url)
            confirm_url = reverse(
                "office:delete_person_from_same_name_candidates",
                args=[household_id, person_id],
            )
            return redirect(
                f"{confirm_url}?{urlencode({'next': safe_return_url, 'delete_result': '1'})}"
            )

    if person.is_deleted and delete_result_mode:
        return render(
            request,
            "office/record_delete_confirm.html",
            {
                "title": "家族レコードを削除",
                "subtitle": f"{person.name or person.person_uid} / 台帳ID {household_id}",
                "delete_result_heading": "家族レコードを削除しました。",
                "delete_result_message": (
                    f"{person.name or person.person_uid} は非表示になりました。"
                ),
                "deleted_meta": {
                    "deleted_at": person.deleted_at,
                    "deleted_by": person.deleted_by,
                    "deletion_note": person.deletion_note,
                },
                "next_url": safe_return_url,
                "return_url": safe_return_url,
                "return_label": _deleted_record_return_label(
                    safe_return_url,
                    household_id=household_id,
                ),
            },
        )

    return redirect(safe_return_url)


@require_POST
def bulk_update_people_gender(request: HttpRequest) -> HttpResponse:
    _canonical_ledger_context()
    next_url = _resolve_next_url(
        request,
        reverse("office:data_quality"),
    )

    male_people: set[tuple[str, str]] = set()
    female_people: set[tuple[str, str]] = set()
    for field_name, target in (("male_people", male_people), ("female_people", female_people)):
        for value in request.POST.getlist(field_name):
            household_key, separator, person_key = (value or "").partition(":")
            household_key = household_key.strip()
            person_key = person_key.strip()
            if not separator or not household_key or not person_key:
                continue
            target.add((household_key, person_key))

    selected_people = male_people | female_people
    if not selected_people:
        messages.warning(request, "男か女のチェックを付けた人だけ更新できます。")
        return redirect(next_url)

    change_note = (request.POST.get("change_note") or "").strip() or "データ問題点一覧で性別を一括更新"
    conflicted_people = male_people & female_people
    updated_male_count = 0
    updated_female_count = 0
    unchanged_count = 0
    with transaction.atomic():
        for household_key, person_key in selected_people:
            if (household_key, person_key) in conflicted_people:
                continue
            person = (
                Person.objects.select_related("household", "deceased_profile")
                .filter(
                    household__household_uid=household_key,
                    person_uid=person_key,
                )
                .first()
            )
            if person is None:
                continue
            target_gender = "男" if (household_key, person_key) in male_people else "女"
            if person.gender == target_gender:
                unchanged_count += 1
                continue
            before_data = _serialize_person_record(person)
            person.gender = target_gender
            person.save(update_fields=["gender", "updated_at"])
            person = _person_for_edit(person.pk)
            _create_record_edit_log(
                record_type=RecordEditLog.RecordType.PERSON,
                record=person,
                before_data=before_data,
                after_data=_serialize_person_record(person),
                editor_label=_request_actor_label(request),
                change_note=change_note,
            )
            if target_gender == "男":
                updated_male_count += 1
            else:
                updated_female_count += 1

    updated_parts = []
    if updated_male_count:
        updated_parts.append(f"男 {updated_male_count}件")
    if updated_female_count:
        updated_parts.append(f"女 {updated_female_count}件")
    if updated_parts:
        messages.success(request, f"チェック内容を反映しました: {' / '.join(updated_parts)}")
    if conflicted_people:
        messages.warning(request, f"男と女の両方にチェックが付いた {len(conflicted_people)} 件は更新していません。")
    if unchanged_count and not updated_parts:
        messages.info(request, f"チェック済み {unchanged_count} 件はすでに指定どおりでした。")
    return redirect(next_url)


def toggle_person_memorial_notice_opt_out(
    request: HttpRequest,
    household_id: str,
    person_id: str,
) -> HttpResponse:
    _canonical_ledger_context()
    person = get_object_or_404(
        Person.objects.select_related("household", "deceased_profile"),
        household__household_uid=household_id,
        person_uid=person_id,
    )
    next_url = _resolve_next_url(
        request,
        _default_household_browser_url(household_id),
    )
    enabled = request.POST.get("enabled") in {"1", "true", "on", "yes"}
    before_data = _serialize_person_record(person)

    with transaction.atomic():
        if not enabled and not person.has_memorial_details():
            return redirect(next_url)
        person.memorial_notice_opt_out = enabled
        if enabled and not person.age_unit:
            person.age_unit = "歳"
        person.save(update_fields=["memorial_notice_opt_out", "age_unit", "updated_at"])
        person.sync_legacy_deceased_profile()
        person = _person_for_edit(person.pk)
        log_entry = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.PERSON,
            record=person,
            before_data=before_data,
            after_data=_serialize_person_record(person),
            editor_label=_request_actor_label(request),
            change_note="戸主ブラウザで年回案内不要を切替",
        )

    _flash_record_action_message(
        request,
        log_entry,
        f"家族レコード {person.person_uid} の年回案内不要を{'オン' if enabled else 'オフ'}にしました。",
    )
    return redirect(next_url)
