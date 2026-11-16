from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.imports.forms_accounting import StandaloneOfferingPaymentForm
from apps.imports.models import Household, OfferingPayment, Person, RecordEditLog
from apps.office.services.record_history_mutations import (
    _create_record_edit_log,
    record_action_message_text,
)
from apps.office.services.record_history_snapshot import _serialize_offering_payment_record
from apps.office.services.record_history_time_machine import _recent_record_history
from apps.office.views.common import _canonical_ledger_context
from apps.office.web_support import (
    _default_household_browser_url,
    _record_action_return_label,
    _request_actor_label,
    _resolve_next_url,
)


def create_household_offering_payment(request: HttpRequest, household_id: str) -> HttpResponse:
    household = _household_for_payment(household_id)
    return _standalone_offering_payment_response(
        request,
        household=household,
        payment=None,
        initial_person=None,
    )


def create_person_offering_payment(
    request: HttpRequest,
    household_id: str,
    person_id: str,
) -> HttpResponse:
    household = _household_for_payment(household_id)
    person = _household_person_for_payment(household, person_id)
    return _standalone_offering_payment_response(
        request,
        household=household,
        payment=None,
        initial_person=person,
    )


def edit_household_offering_payment(
    request: HttpRequest,
    household_id: str,
    payment_id: int,
) -> HttpResponse:
    payment = _standalone_offering_payment_for_edit(household_id, payment_id)
    household = payment.household or _household_for_payment(household_id)
    return _standalone_offering_payment_response(
        request,
        household=household,
        payment=payment,
        initial_person=None,
    )


def _standalone_offering_payment_response(
    request: HttpRequest,
    *,
    household: Household,
    payment: OfferingPayment | None,
    initial_person: Person | None,
) -> HttpResponse:
    next_url = _resolve_next_url(
        request,
        _default_household_browser_url(household.household_uid, focus="detail"),
    )
    return_label = _record_action_return_label(
        next_url,
        household_id=household.household_uid,
    )
    person_queryset = (
        Person.objects.filter(
            household=household,
            deleted_at__isnull=True,
        )
        .order_by("family_category", "person_uid")
    )
    instance = payment or OfferingPayment(household=household, person=initial_person)
    initial = {}
    if request.method == "GET" and initial_person is not None:
        initial["person"] = initial_person
    if request.method == "POST" and request.POST.get("action") == "delete" and payment is not None:
        before_data = _serialize_offering_payment_record(payment)
        with transaction.atomic():
            payment.delete()
            log_entry = _create_record_edit_log(
                record_type=RecordEditLog.RecordType.OFFERING_PAYMENT,
                record=payment,
                before_data=before_data,
                after_data={},
                editor_label=_request_actor_label(request),
                change_note=request.POST.get("change_note", ""),
                action_kind=RecordEditLog.ActionKind.DELETE,
            )
        messages.success(
            request,
            record_action_message_text(log_entry, "入金を削除しました。"),
        )
        return redirect(next_url)

    if request.method == "POST":
        before_data = _serialize_offering_payment_record(payment) if payment is not None else {}
        form = StandaloneOfferingPaymentForm(
            request.POST,
            instance=instance,
            household=household,
            person_queryset=person_queryset,
        )
        if form.is_valid():
            with transaction.atomic():
                saved_payment = form.save(commit=False)
                saved_payment.household = household
                saved_payment.service_schedule = None
                saved_payment.is_demo_data = False
                if (
                    before_data.get("person_id") is not None
                    and request.POST.get("person") == ""
                    and saved_payment.person_id is None
                ):
                    saved_payment.person_uid = ""
                    saved_payment.person_name_snapshot = ""
                saved_payment.save()
                saved_payment = _standalone_offering_payment_by_pk(saved_payment.pk)
                log_entry = _create_record_edit_log(
                    record_type=RecordEditLog.RecordType.OFFERING_PAYMENT,
                    record=saved_payment,
                    before_data=before_data,
                    after_data=_serialize_offering_payment_record(saved_payment),
                    editor_label=_request_actor_label(request),
                    change_note=request.POST.get("change_note", ""),
                )
            message_text = "入金を保存しました。"
            if payment is None:
                message_text = "入金を登録しました。"
            messages.success(request, record_action_message_text(log_entry, message_text))
            return redirect(next_url)
    else:
        form = StandaloneOfferingPaymentForm(
            instance=instance,
            initial=initial,
            household=household,
            person_queryset=person_queryset,
        )

    history_entries = []
    if payment is not None and payment.pk:
        history_entries = _recent_record_history(
            RecordEditLog.RecordType.OFFERING_PAYMENT,
            payment.pk,
        )
    subtitle_parts = [household.display_head_name()]
    if payment is not None and payment.person_id and payment.person is not None:
        subtitle_parts.append(payment.person.name or payment.person.person_uid)
    elif initial_person is not None:
        subtitle_parts.append(initial_person.name or initial_person.person_uid)
    return render(
        request,
        "office/record_edit.html",
        {
            "title": "入金を編集" if payment is not None else "法要外入金を追加",
            "subtitle": " / ".join(subtitle_parts),
            "form": form,
            "next_url": next_url,
            "return_label": return_label,
            "change_note": request.POST.get("change_note", ""),
            "warning_message": (
                "法要外の入金をこの家に紐づけて記録します。"
                " 法要に紐づけたい入金は法要編集から入力してください。"
            ),
            "record_deleted": False,
            "deleted_meta": {},
            "history_entries": history_entries,
            "linked_schedule_members": [],
            "can_delete": payment is not None,
            "delete_button_label": "この入金を削除",
            "delete_confirm_text": "この入金を完全に削除します。よろしいですか？",
            "submit_label": "保存" if payment is not None else "登録",
            "payment_formset": None,
            "payment_summary": [],
            "read_only_mode": False,
            "time_machine_mode": False,
            "supports_time_machine": False,
        },
    )


def _household_for_payment(household_id: str) -> Household:
    _canonical_ledger_context()
    return get_object_or_404(
        Household.objects.select_related("head_person"),
        household_uid=household_id,
    )


def _household_person_for_payment(household: Household, person_id: str) -> Person:
    return get_object_or_404(
        Person.objects.select_related("household"),
        household=household,
        person_uid=person_id,
        deleted_at__isnull=True,
    )


def _standalone_offering_payment_for_edit(household_id: str, payment_id: int) -> OfferingPayment:
    _canonical_ledger_context()
    return get_object_or_404(
        OfferingPayment.objects.select_related("household", "person", "service_schedule"),
        pk=payment_id,
        household_uid=household_id,
        service_schedule__isnull=True,
    )


def _standalone_offering_payment_by_pk(payment_pk: int | None) -> OfferingPayment:
    return OfferingPayment.objects.select_related("household", "person", "service_schedule").get(pk=payment_pk)
