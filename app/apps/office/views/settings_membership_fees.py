from __future__ import annotations

from django.contrib import messages
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.imports.forms import AnnualMembershipFeeEntryForm, AnnualMembershipFeeSettingForm
from apps.imports.models import (
    AnnualMembershipFeeCheckSheetScan,
    AnnualMembershipFeePostalScan,
    AnnualMembershipFeeSetting,
    Household,
)
from apps.office.services import (
    annual_membership_fee_check_sheet_records as check_sheet_record_services,
)
from apps.office.services import (
    annual_membership_fee_context as annual_membership_fee_context_services,
)
from apps.office.services import (
    annual_membership_fee_mutations as annual_membership_fee_mutation_services,
)
from apps.office.services import annual_membership_fee_postal_scans as postal_scan_services
from apps.office.services.annual_membership_fee_check_sheet_pdf import (
    render_annual_membership_fee_check_sheet_pdf,
)
from apps.office.services.annual_membership_fee_check_sheet_scan import (
    CheckSheetScanError,
    render_check_sheet_scan_pdf_preview_png,
)
from apps.office.services.household_editing_core import _household_display_head_name
from apps.office.views.common import (
    _ensure_source_record,
    _request_actor_label,
    _resolve_editable_batch,
)
from apps.office.web_support import (
    _annual_membership_fee_check_sheets_url,
    _annual_membership_fee_postal_scan_anchor_url,
    _annual_membership_fee_postal_scans_url,
    _annual_membership_fees_url,
    _parse_optional_year,
)

_annual_membership_fee_receipt_temple_name = (
    annual_membership_fee_context_services._annual_membership_fee_receipt_temple_name
)
_build_annual_membership_fee_receipt_context = (
    annual_membership_fee_context_services._build_annual_membership_fee_receipt_context
)
_build_annual_membership_fee_check_sheet_context = (
    annual_membership_fee_context_services._build_annual_membership_fee_check_sheet_context
)
_build_annual_membership_fee_context = (
    annual_membership_fee_context_services._build_annual_membership_fee_context
)


def annual_membership_fees(request: HttpRequest) -> HttpResponse:
    active_source_id, batch = _resolve_editable_batch(None)
    source_record = _ensure_source_record(active_source_id)
    year = _parse_optional_year(request.GET.get("year") or request.POST.get("year")) or timezone.localdate().year
    payment_status = annual_membership_fee_context_services.normalize_annual_membership_fee_payment_status(
        request.GET.get("payment_status") or request.POST.get("payment_status")
    )
    return_url = _annual_membership_fees_url(
        year=year,
        payment_status=payment_status,
    )
    if payment_status:
        return_url += "#membership-fee-list"
    setting = (
        AnnualMembershipFeeSetting.objects.filter(source=source_record, year=year).first()
        or AnnualMembershipFeeSetting(source=source_record, year=year)
    )
    row_form_overrides: dict[str, AnnualMembershipFeeEntryForm] = {}

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "save_setting":
            setting_form = AnnualMembershipFeeSettingForm(request.POST, instance=setting, prefix="setting")
            if setting_form.is_valid():
                messages.success(
                    request,
                    annual_membership_fee_mutation_services.save_annual_membership_fee_setting(
                        setting_form=setting_form,
                        source_record=source_record,
                        year=year,
                        editor_label=_request_actor_label(request),
                    ),
                )
                return redirect(return_url)
        else:
            household_id = (request.POST.get("household_id") or "").strip()
            row_prefix = f"row-{household_id}"
            row_action = (request.POST.get("row_action") or "receive").strip()
            row_post_data = request.POST.copy()
            if row_action == "receive" or row_action.startswith("confirm_postal_scan:"):
                row_post_data[f"{row_prefix}-paid"] = "on"
            else:
                row_post_data.pop(f"{row_prefix}-paid", None)
            row_form = AnnualMembershipFeeEntryForm(row_post_data, prefix=row_prefix)
            row_form_overrides[household_id] = row_form
            if row_form.is_valid():
                household = get_object_or_404(
                    Household.objects.select_related("head_person"),
                    household_uid=household_id,
                    deleted_at__isnull=True,
                )
                if row_action.startswith("confirm_postal_scan:"):
                    try:
                        scan_id = int(row_action.split(":", 1)[1])
                    except (IndexError, ValueError) as exc:
                        raise Http404("unknown postal scan") from exc
                    scan = get_object_or_404(
                        AnnualMembershipFeePostalScan,
                        pk=scan_id,
                        source=source_record,
                        year=year,
                    )
                    postal_result = postal_scan_services.confirm_postal_scan_payment(
                        active_source_id=active_source_id,
                        source_record=source_record,
                        batch=batch,
                        scan=scan,
                        selected_household_id=household.household_uid,
                        year=year,
                        received_on=row_form.cleaned_data.get("received_on"),
                        default_amount=setting.default_amount,
                        actor_label=_request_actor_label(request),
                    )
                    if postal_result.success:
                        messages.success(request, postal_result.message)
                    else:
                        messages.error(request, postal_result.message)
                    if postal_result.move_error:
                        messages.error(request, postal_result.move_error)
                    return redirect(return_url)
                result = annual_membership_fee_mutation_services.apply_annual_membership_fee_row_action(
                    active_source_id=active_source_id,
                    source_record=source_record,
                    year=year,
                    household=household,
                    row_action=row_action,
                    row_form=row_form,
                    default_amount=setting.default_amount,
                    editor_label=_request_actor_label(request),
                )
                if result.should_redirect:
                    if result.message_level == "error":
                        messages.error(request, result.message)
                    elif result.message_level == "success":
                        messages.success(request, result.message)
                    return redirect(return_url)
            setting_form = AnnualMembershipFeeSettingForm(instance=setting, prefix="setting")
    else:
        setting_form = AnnualMembershipFeeSettingForm(instance=setting, prefix="setting")

    context = _build_annual_membership_fee_context(
        source_id=active_source_id,
        batch=batch,
        source_record=source_record,
        year=year,
        setting_form=setting_form,
        row_form_overrides=row_form_overrides,
        payment_status=payment_status,
    )
    return render(request, "office/annual_membership_fees.html", context)


def annual_membership_fee_receipts(request: HttpRequest) -> HttpResponse:
    active_source_id, batch = _resolve_editable_batch(None)
    source_record = _ensure_source_record(active_source_id)
    year = _parse_optional_year(request.GET.get("year") or request.POST.get("year")) or timezone.localdate().year
    context = _build_annual_membership_fee_receipt_context(
        source_id=active_source_id,
        batch=batch,
        source_record=source_record,
        year=year,
    )
    return render(request, "office/annual_membership_fee_receipts.html", context)


def annual_membership_fee_check_sheets(request: HttpRequest) -> HttpResponse:
    active_source_id, batch = _resolve_editable_batch(None)
    source_record = _ensure_source_record(active_source_id)
    year = _parse_optional_year(request.GET.get("year") or request.POST.get("year")) or timezone.localdate().year
    setting = (
        AnnualMembershipFeeSetting.objects.filter(source=source_record, year=year).first()
        or AnnualMembershipFeeSetting(source=source_record, year=year)
    )
    context = _build_annual_membership_fee_check_sheet_context(
        source_id=active_source_id,
        batch=batch,
        source_record=source_record,
        year=year,
    )
    context["received_on_default"] = timezone.localdate()
    requested_mode = (request.GET.get("mode") or "").strip().lower()
    view_mode = "review" if request.method == "POST" or requested_mode == "review" else "print"
    context["view_mode"] = view_mode
    context["print_url"] = _annual_membership_fee_check_sheets_url(year=year, mode="print")
    context["review_url"] = _annual_membership_fee_check_sheets_url(year=year, mode="review")
    context["current_url"] = context["review_url"] if view_mode == "review" else context["print_url"]

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        received_on = parse_date(request.POST.get("received_on") or "") or timezone.localdate()
        context["received_on_default"] = received_on
        if action == "scan_upload":
            uploaded_file = request.FILES.get("scan_file")
            if uploaded_file is None:
                messages.error(request, "スキャン画像またはPDFを選択してください。")
            else:
                try:
                    saved_scan = check_sheet_record_services.save_check_sheet_scan(
                        context=context,
                        source_record=source_record,
                        year=year,
                        uploaded_file=uploaded_file,
                        uploaded_by=_request_actor_label(request),
                    )
                    context["scan_result"] = saved_scan.result
                    context["scan_record"] = saved_scan.record
                    if saved_scan.created:
                        messages.success(request, "読取に使った原本を保存しました。")
                    elif saved_scan.record.status == AnnualMembershipFeeCheckSheetScan.Status.CONFIRMED:
                        messages.info(request, "同じ原本はすでに保存され、受領へ反映済みです。")
                    else:
                        messages.info(request, "同じ原本の保存済み読取記録を開きました。")
                except (
                    CheckSheetScanError,
                    check_sheet_record_services.CheckSheetScanRecordError,
                ) as exc:
                    messages.error(request, exc.message)
        elif action == "confirm_scan":
            selected_household_ids = request.POST.getlist("household_id")
            try:
                scan_id = int(request.POST.get("scan_id") or "")
                if scan_id <= 0:
                    raise ValueError
            except ValueError:
                messages.error(request, "保存済みの読取記録を確認できませんでした。")
            else:
                try:
                    _scan, result = check_sheet_record_services.confirm_check_sheet_scan(
                        scan_id=scan_id,
                        active_source_id=active_source_id,
                        source_record=source_record,
                        batch=batch,
                        year=year,
                        household_ids=selected_household_ids,
                        received_on=received_on,
                        default_amount=setting.default_amount,
                        confirmed_by=_request_actor_label(request),
                    )
                except check_sheet_record_services.CheckSheetScanRecordError as exc:
                    messages.error(request, exc.message)
                else:
                    messages.success(request, f"{result.saved_count}件を受領済みにしました。")
                    return redirect(_annual_membership_fees_url(year=year))

    if (
        request.method == "GET"
        and (request.GET.get("format") or "").strip().lower() == "pdf"
        and context.get("available")
    ):
        response = HttpResponse(
            render_annual_membership_fee_check_sheet_pdf(context=context),
            content_type="application/pdf",
        )
        response["Content-Disposition"] = (
            f'inline; filename="annual-membership-fee-check-sheet-{year}.pdf"'
        )
        return response
    if view_mode == "review":
        context["scan_history"] = check_sheet_record_services.recent_check_sheet_scans(
            source_record=source_record,
            year=year,
        )
    return render(request, "office/annual_membership_fee_check_sheets.html", context)


def annual_membership_fee_postal_scans(request: HttpRequest) -> HttpResponse:
    active_source_id, batch = _resolve_editable_batch(None)
    source_record = _ensure_source_record(active_source_id)
    year = _parse_optional_year(request.GET.get("year") or request.POST.get("year")) or timezone.localdate().year
    setting = (
        AnnualMembershipFeeSetting.objects.filter(source=source_record, year=year).first()
        or AnnualMembershipFeeSetting(source=source_record, year=year)
    )
    wants_json = request.headers.get("x-requested-with") == "XMLHttpRequest"

    if request.method == "GET" and (request.GET.get("format") or "").strip() == "ocr-progress":
        return JsonResponse(postal_scan_services.read_postal_scan_ocr_progress(year=year))

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "upload_pdfs":
            uploaded_files = request.FILES.getlist("pdf_files")
            if not uploaded_files:
                messages.error(request, "アップロードするPDFを選択してください。")
                return redirect(_annual_membership_fee_postal_scans_url(year=year))
            result = postal_scan_services.upload_postal_scan_pdfs(
                source_record=source_record,
                batch=batch,
                year=year,
                uploaded_files=uploaded_files,
            )
            if result.uploaded_count:
                messages.success(request, f"{result.uploaded_count}個のPDFをアップロードしました。")
            if result.imported_count:
                messages.success(request, f"{result.imported_count}件の振込ページを読み込みました。")
            if result.skipped_count:
                messages.warning(request, f"{result.skipped_count}件は登録済みPDFとしてスキップしました。")
            for skipped_message in result.skipped_messages:
                messages.warning(request, skipped_message)
            for error_message in result.error_messages:
                messages.error(request, error_message)
            return redirect(_annual_membership_fee_postal_scans_url(year=year))
        if action == "scan_pending":
            result = postal_scan_services.intake_postal_scan_pdfs(
                source_record=source_record,
                batch=batch,
                year=year,
            )
            if result.imported_count:
                messages.success(request, f"{result.imported_count}件のPDFを読み込みました。")
            if result.skipped_count:
                messages.success(request, f"{result.skipped_count}件は登録済みPDFとしてスキップしました。")
            for error_message in result.error_messages:
                messages.error(request, error_message)
            return redirect(_annual_membership_fee_postal_scans_url(year=year))
        if action == "stop_ai_ocr":
            postal_scan_services.request_postal_scan_ocr_stop(year=year)
            if wants_json:
                return JsonResponse(postal_scan_services.read_postal_scan_ocr_progress(year=year))
            messages.success(request, "AI OCRの停止を要求しました。現在処理中の1件が終わったら停止します。")
            return redirect(_annual_membership_fee_postal_scans_url(year=year))
        if action == "run_ai_ocr":
            start_result = postal_scan_services.start_postal_scan_ocr_batch(
                source_record=source_record,
                batch=batch,
                year=year,
                force=(request.POST.get("force") or "").strip() in {"1", "true", "on"},
            )
            if wants_json:
                return JsonResponse(
                    {
                        "started": start_result.started,
                        "message": start_result.message,
                        "progress": start_result.progress,
                    }
                )
            if start_result.started:
                messages.success(request, start_result.message)
            else:
                messages.error(request, start_result.message)
            return redirect(_annual_membership_fee_postal_scans_url(year=year))
        if action == "save_candidate_phone":
            scan_id = (request.POST.get("scan_id") or "").strip()
            result = postal_scan_services.save_postal_scan_candidate_phone(
                source_record=source_record,
                batch=batch,
                selected_household_id=(request.POST.get("household_id") or "").strip(),
                phone=request.POST.get("phone") or "",
                phone_target=request.POST.get("phone_target") or "",
                actor_label=_request_actor_label(request),
            )
            if result.success:
                messages.success(request, result.message)
            else:
                messages.error(request, result.message)
            return redirect(_annual_membership_fee_postal_scan_anchor_url(year=year, scan_id=scan_id))
        if action == "save_candidate_contact":
            scan_id = (request.POST.get("scan_id") or "").strip()
            result = postal_scan_services.save_postal_scan_candidate_contact(
                source_record=source_record,
                batch=batch,
                selected_household_id=(request.POST.get("household_id") or "").strip(),
                postal_code=request.POST.get("postal_code") or "",
                address_line1=request.POST.get("address_line1") or "",
                address_line2=request.POST.get("address_line2") or "",
                address_line3=request.POST.get("address_line3") or "",
                phone=request.POST.get("phone") or "",
                mobile=request.POST.get("mobile") or "",
                mailing_phone=request.POST.get("mailing_phone") or "",
                actor_label=_request_actor_label(request),
            )
            if result.success:
                messages.success(request, result.message)
            else:
                messages.error(request, result.message)
            return redirect(_annual_membership_fee_postal_scan_anchor_url(year=year, scan_id=scan_id))
        if action == "search_scan":
            scan = get_object_or_404(
                AnnualMembershipFeePostalScan,
                pk=request.POST.get("scan_id"),
                source=source_record,
                year=year,
            )
            postal_scan_services.update_postal_scan_search_candidates(
                scan=scan,
                batch=batch,
                source_record=source_record,
                query=request.POST.get("q") or "",
            )
            return redirect(_annual_membership_fee_postal_scan_anchor_url(year=year, scan_id=scan.id))
        if action == "run_ai_reasoning":
            scan = get_object_or_404(
                AnnualMembershipFeePostalScan,
                pk=request.POST.get("scan_id"),
                source=source_record,
                year=year,
            )
            result = postal_scan_services.run_postal_scan_ai_reasoning(
                source_record=source_record,
                batch=batch,
                scan=scan,
                year=year,
                actor_label=_request_actor_label(request),
            )
            if result.success:
                messages.success(request, result.message)
            else:
                messages.error(request, result.message)
            return redirect(
                _annual_membership_fee_postal_scan_anchor_url(
                    year=year,
                    scan_id=scan.id,
                )
            )
        if action == "confirm_scan":
            scan = get_object_or_404(
                AnnualMembershipFeePostalScan,
                pk=request.POST.get("scan_id"),
                source=source_record,
                year=year,
            )
            was_checked = scan.status == AnnualMembershipFeePostalScan.Status.CHECKED
            result = postal_scan_services.confirm_postal_scan_payment(
                active_source_id=active_source_id,
                source_record=source_record,
                batch=batch,
                scan=scan,
                selected_household_id=(request.POST.get("household_id") or "").strip(),
                year=year,
                received_on=parse_date(request.POST.get("received_on") or ""),
                default_amount=setting.default_amount,
                actor_label=_request_actor_label(request),
                allow_reedit=(request.POST.get("reedit") or "").strip() == "1",
            )
            if result.success:
                messages.success(request, result.message)
            else:
                messages.error(request, result.message)
            if result.move_error:
                messages.error(request, result.move_error)
            if result.success and not result.move_error and not was_checked:
                next_scan_id = postal_scan_services.next_postal_scan_requiring_action_id(
                    source_record=source_record,
                    year=year,
                )
                if next_scan_id is not None:
                    return redirect(
                        _annual_membership_fee_postal_scan_anchor_url(
                            year=year,
                            scan_id=next_scan_id,
                        )
                    )
                return redirect(
                    f"{_annual_membership_fee_postal_scans_url(year=year)}#postal-scan-worklist"
                )
            return redirect(_annual_membership_fee_postal_scan_anchor_url(year=year, scan_id=scan.id))
        if action == "mark_unknown_payment":
            scan = get_object_or_404(
                AnnualMembershipFeePostalScan,
                pk=request.POST.get("scan_id"),
                source=source_record,
                year=year,
            )
            was_checked = scan.status == AnnualMembershipFeePostalScan.Status.CHECKED
            result = postal_scan_services.mark_postal_scan_unknown_payment(
                source_record=source_record,
                scan=scan,
                year=year,
                note=request.POST.get("unknown_note") or "",
                actor_label=_request_actor_label(request),
                allow_reedit=(request.POST.get("reedit") or "").strip() == "1",
            )
            if result.success:
                messages.success(request, result.message)
            else:
                messages.error(request, result.message)
            if result.move_error:
                messages.error(request, result.move_error)
            if result.success and not result.move_error and not was_checked:
                next_scan_id = postal_scan_services.next_postal_scan_requiring_action_id(
                    source_record=source_record,
                    year=year,
                )
                if next_scan_id is not None:
                    return redirect(
                        _annual_membership_fee_postal_scan_anchor_url(
                            year=year,
                            scan_id=next_scan_id,
                        )
                    )
                return redirect(
                    f"{_annual_membership_fee_postal_scans_url(year=year)}#postal-scan-worklist"
                )
            return redirect(_annual_membership_fee_postal_scan_anchor_url(year=year, scan_id=scan.id))
        if action == "retry_move":
            scan = get_object_or_404(
                AnnualMembershipFeePostalScan,
                pk=request.POST.get("scan_id"),
                source=source_record,
                year=year,
            )
            result = postal_scan_services.retry_postal_scan_pdf_move(scan)
            if result.success:
                messages.success(request, result.message)
            else:
                messages.error(request, result.message)
            if result.move_error:
                messages.error(request, result.move_error)
            return redirect(_annual_membership_fee_postal_scan_anchor_url(year=year, scan_id=scan.id))

    context = postal_scan_services.build_postal_scan_review_context(
        source_id=active_source_id,
        source_record=source_record,
        batch=batch,
        year=year,
    )
    context.update(
        {
            "fees_url": _annual_membership_fees_url(year=year),
            "current_url": _annual_membership_fee_postal_scans_url(year=year),
            "ocr_progress_url": f"{_annual_membership_fee_postal_scans_url(year=year)}&format=ocr-progress",
            "default_amount": setting.default_amount or 0,
        }
    )
    return render(request, "office/annual_membership_fee_postal_scans.html", context)

def annual_membership_fee_postal_scan_file(
    request: HttpRequest,
    scan_id: int,
    kind: str,
) -> HttpResponse:
    if kind not in {"pdf", "page", "crop"}:
        raise Http404("unknown postal scan file kind")
    active_source_id, _batch = _resolve_editable_batch(None)
    source_record = _ensure_source_record(active_source_id)
    scan = get_object_or_404(AnnualMembershipFeePostalScan, pk=scan_id, source=source_record)
    try:
        path = postal_scan_services.postal_scan_file_path(scan, kind=kind)
    except (FileNotFoundError, ValueError) as exc:
        raise Http404("postal scan file not found") from exc
    content_type = "application/pdf" if kind == "pdf" else "image/png"
    return FileResponse(path.open("rb"), content_type=content_type, filename=path.name)


def annual_membership_fee_check_sheet_scan_detail(
    request: HttpRequest,
    scan_id: int,
) -> HttpResponse:
    active_source_id, _batch = _resolve_editable_batch(None)
    source_record = _ensure_source_record(active_source_id)
    scan = get_object_or_404(
        AnnualMembershipFeeCheckSheetScan,
        pk=scan_id,
        source=source_record,
    )
    try:
        check_sheet_record_services.check_sheet_scan_file_path(scan)
    except (FileNotFoundError, ValueError) as exc:
        raise Http404("check sheet scan file not found") from exc
    return render(
        request,
        "office/annual_membership_fee_check_sheet_scan_detail.html",
        {
            "scan": scan,
            "is_pdf": scan.content_type == "application/pdf",
            "review_url": _annual_membership_fee_check_sheets_url(
                year=scan.year,
                mode="review",
            ),
            "fees_url": _annual_membership_fees_url(year=scan.year),
        },
    )


def annual_membership_fee_check_sheet_scan_file(
    request: HttpRequest,
    scan_id: int,
) -> HttpResponse:
    active_source_id, _batch = _resolve_editable_batch(None)
    source_record = _ensure_source_record(active_source_id)
    scan = get_object_or_404(
        AnnualMembershipFeeCheckSheetScan,
        pk=scan_id,
        source=source_record,
    )
    try:
        path = check_sheet_record_services.check_sheet_scan_file_path(scan)
    except (FileNotFoundError, ValueError) as exc:
        raise Http404("check sheet scan file not found") from exc
    content_type = scan.content_type
    if content_type != "application/pdf" and not content_type.startswith("image/"):
        content_type = "application/octet-stream"
    if content_type == "application/pdf" and request.GET.get("preview") == "1":
        try:
            preview_bytes = render_check_sheet_scan_pdf_preview_png(path.read_bytes())
        except CheckSheetScanError as exc:
            raise Http404("check sheet scan preview not available") from exc
        response = HttpResponse(preview_bytes, content_type="image/png")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    response = FileResponse(
        path.open("rb"),
        as_attachment=False,
        content_type=content_type,
        filename=scan.original_filename,
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


__all__ = [
    "_annual_membership_fee_receipt_temple_name",
    "_build_annual_membership_fee_check_sheet_context",
    "_build_annual_membership_fee_receipt_context",
    "_build_annual_membership_fee_context",
    "_household_display_head_name",
    "annual_membership_fee_check_sheet_scan_detail",
    "annual_membership_fee_check_sheet_scan_file",
    "annual_membership_fee_check_sheets",
    "annual_membership_fee_postal_scan_file",
    "annual_membership_fee_postal_scans",
    "annual_membership_fee_receipts",
    "annual_membership_fees",
]
