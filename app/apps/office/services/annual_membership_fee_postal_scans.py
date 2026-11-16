from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from django.db import close_old_connections, transaction
from django.utils import timezone

import apps.office.services.annual_membership_fee_postal_scan_artifacts as artifact_services
import apps.office.services.annual_membership_fee_postal_scan_jobs as job_services
import apps.office.services.annual_membership_fee_postal_scan_matching as matching_services
import apps.office.services.annual_membership_fee_postal_scan_ocr as ocr_services
import apps.office.services.annual_membership_fee_postal_scan_payments as payment_services
import apps.office.services.annual_membership_fee_postal_scan_pdf_moves as pdf_move_services
import apps.office.services.annual_membership_fee_postal_scan_reasoning as reasoning_services
import apps.office.services.annual_membership_fee_postal_scan_receipts as receipt_services
import apps.office.services.annual_membership_fee_postal_scan_statement_dates as statement_date_services
import apps.office.services.annual_membership_fee_postal_scan_storage as storage_services
from apps.imports.models import (
    FAMILY_CATEGORY_CURRENT,
    HOUSEHOLD_DELIVERY_LABELS,
    AnnualMembershipFeePayment,
    AnnualMembershipFeePostalScan,
    Household,
    HouseholdProfile,
    ImportBatch,
    LegacySource,
    Person,
    RecordEditLog,
)
from apps.office.services.annual_membership_fee_context import (
    ANNUAL_MEMBERSHIP_FEE_NO_NOTICE_EXCLUSION_REASON,
    _annual_membership_fee_exclusion_reason,
)
from apps.office.services.household_editing_core import (
    _household_display_head_name,
    _household_display_head_name_kana,
)
from apps.office.services.record_history_mutations import (
    _create_record_edit_log,
    record_action_message_text,
)
from apps.office.services.record_history_snapshot import _serialize_household_record
from config import runtime_paths as runtime_paths

POSTAL_SCAN_ROOT_NAME = storage_services.POSTAL_SCAN_ROOT_NAME
POSTAL_SCAN_PAYMENT_NOTE = payment_services.POSTAL_SCAN_PAYMENT_NOTE
POSTAL_SCAN_NO_NOTICE_PAYMENT_NOTE = payment_services.POSTAL_SCAN_NO_NOTICE_PAYMENT_NOTE
POSTAL_SCAN_UNKNOWN_PAYMENT_LABEL = payment_services.POSTAL_SCAN_UNKNOWN_PAYMENT_LABEL
PAGE_RENDER_SCALE = artifact_services.PAGE_RENDER_SCALE
OPENAI_RESPONSES_URL = ocr_services.OPENAI_RESPONSES_URL
POSTAL_SCAN_OCR_MODEL = ocr_services.POSTAL_SCAN_OCR_MODEL
POSTAL_SCAN_OCR_TIMEOUT_SECONDS = ocr_services.POSTAL_SCAN_OCR_TIMEOUT_SECONDS
DEFAULT_NAME_CROP_BOX = artifact_services.DEFAULT_NAME_CROP_BOX
WAREKI_ERA_OFFSETS = statement_date_services.WAREKI_ERA_OFFSETS

_POSTAL_SCAN_WORKLIST_STATUS_ORDER = {
    AnnualMembershipFeePostalScan.Status.MOVE_ERROR: 0,
    AnnualMembershipFeePostalScan.Status.NEEDS_REVIEW: 1,
    AnnualMembershipFeePostalScan.Status.PENDING: 2,
    AnnualMembershipFeePostalScan.Status.CHECKED: 3,
}


@dataclass(slots=True)
class PostalScanImportResult:
    imported_count: int
    skipped_count: int
    error_messages: list[str]


@dataclass(slots=True)
class PostalScanUploadResult:
    uploaded_count: int
    imported_count: int
    skipped_count: int
    skipped_messages: list[str]
    error_messages: list[str]


@dataclass(slots=True)
class PostalScanOcrBatchResult:
    processed_count: int
    skipped_count: int
    error_messages: list[str]
    stopped: bool = False


@dataclass(slots=True)
class PostalScanOcrStartResult:
    started: bool
    message: str
    progress: dict


@dataclass(slots=True)
class PostalScanPhoneSaveResult:
    success: bool
    message: str


@dataclass(slots=True)
class PostalScanContactSaveResult:
    success: bool
    message: str


@dataclass(slots=True)
class PostalScanConfirmResult:
    success: bool
    message: str
    move_error: str = ""


@dataclass(slots=True)
class PostalScanReasoningRunResult:
    success: bool
    message: str


@dataclass(slots=True)
class PostalScanVerificationIssue:
    scan_id: int
    storage_key: str
    kind: str
    message: str


@dataclass(slots=True)
class _PostalScanCandidatePopulation:
    households: list[Household]
    profiles: dict[str, HouseholdProfile]
    member_names_by_household_pk: dict[int, list[tuple[str, str]]]
    paid_household_uids: set[str]
    payments_by_household_uid: dict[str, AnnualMembershipFeePayment]


PostalScanOcrError = ocr_services.PostalScanOcrError
PostalScanOcrClient = ocr_services.PostalScanOcrClient
PostalScanReasoningClient = reasoning_services.PostalScanReasoningClient
PostalScanReasoningError = reasoning_services.PostalScanReasoningError
calculate_file_sha256 = storage_services.calculate_file_sha256


def _active_canonical_households(*, source_id: str):
    return payment_services.active_canonical_households(source_id=source_id)


def _build_postal_scan_candidate_population(
    *,
    source_record: LegacySource,
    year: int | None = None,
) -> _PostalScanCandidatePopulation:
    households = list(
        _active_canonical_households(source_id=source_record.source_id).select_related(
            "head_person"
        )
    )
    household_uids = [household.household_uid for household in households]
    profiles = {
        profile.household_uid: profile
        for profile in source_record.household_profiles.select_related("district").filter(
            household_uid__in=household_uids,
        )
    }
    member_names_by_household_pk: dict[int, list[tuple[str, str]]] = {}
    head_person_ids = {
        household.pk: household.head_person_id
        for household in households
        if household.pk is not None
    }
    for person in (
        Person.objects.filter(
            household_id__in=head_person_ids,
            deleted_at__isnull=True,
            family_category=FAMILY_CATEGORY_CURRENT,
            is_deceased=False,
        )
        .exclude(name="")
        .values("pk", "household_id", "name", "kana")
    ):
        household_pk = int(person["household_id"])
        if person["pk"] == head_person_ids.get(household_pk):
            continue
        member_names_by_household_pk.setdefault(household_pk, []).append(
            (str(person["name"] or "").strip(), str(person["kana"] or "").strip())
        )
    payments_by_household_uid = (
        {
            payment.household_uid: payment
            for payment in AnnualMembershipFeePayment.objects.filter(
                source=source_record,
                year=year,
            ).order_by("pk")
        }
        if year is not None
        else {}
    )
    return _PostalScanCandidatePopulation(
        households=households,
        profiles=profiles,
        member_names_by_household_pk=member_names_by_household_pk,
        paid_household_uids=set(payments_by_household_uid),
        payments_by_household_uid=payments_by_household_uid,
    )


def postal_scan_storage_root() -> Path:
    return storage_services.postal_scan_storage_root()


def ensure_postal_scan_year_directories(year: int) -> dict[str, Path]:
    return storage_services.ensure_postal_scan_year_directories(
        year,
        storage_root=postal_scan_storage_root(),
    )


def postal_scan_storage_path(storage_key: str) -> Path:
    return storage_services.postal_scan_storage_path(
        storage_key,
        storage_root=postal_scan_storage_root(),
    )


def postal_scan_file_path(scan: AnnualMembershipFeePostalScan, *, kind: str) -> Path:
    return storage_services.postal_scan_file_path(
        scan,
        kind=kind,
        storage_root=postal_scan_storage_root(),
    )


def intake_postal_scan_pdfs(
    *,
    source_record: LegacySource,
    batch: ImportBatch,
    year: int,
) -> PostalScanImportResult:
    paths = ensure_postal_scan_year_directories(year)
    return _intake_postal_scan_pdf_paths(
        source_record=source_record,
        batch=batch,
        year=year,
        pdf_paths=sorted(paths["pending"].glob("*.pdf")),
    )


def upload_postal_scan_pdfs(
    *,
    source_record: LegacySource,
    batch: ImportBatch,
    year: int,
    uploaded_files,
) -> PostalScanUploadResult:
    ensure_postal_scan_year_directories(year)
    uploaded_count = 0
    skipped_count = 0
    skipped_messages: list[str] = []
    error_messages: list[str] = []
    saved_paths: list[Path] = []
    for uploaded_file in uploaded_files:
        original_filename = _safe_filename(getattr(uploaded_file, "name", "") or "scan.pdf")
        if Path(original_filename).suffix.lower() != ".pdf":
            error_messages.append(f"{original_filename}: PDFファイルだけアップロードできます。")
            continue
        temp_key = _available_storage_key(f"{year}/pending/.upload-{uuid4().hex}.pdf")
        temp_path = postal_scan_storage_path(temp_key)
        try:
            _write_uploaded_file(uploaded_file, temp_path)
            if temp_path.stat().st_size <= 0:
                raise ValueError("空のPDFファイルです。")
            pdf_sha256 = calculate_file_sha256(temp_path)
            duplicate_label = _existing_postal_scan_pdf_label_by_sha256(
                source_record=source_record,
                year=year,
                pdf_sha256=pdf_sha256,
                exclude_path=temp_path,
            )
            if duplicate_label:
                skipped_count += 1
                skipped_messages.append(
                    f"{original_filename}: 同一内容のPDFは登録済みです（{duplicate_label}）。"
                )
                temp_path.unlink(missing_ok=True)
                continue
            destination_path = _pending_upload_destination_path(
                year=year,
                original_filename=original_filename,
                pdf_sha256=pdf_sha256,
            )
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temp_path), str(destination_path))
            saved_paths.append(destination_path)
            uploaded_count += 1
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            error_messages.append(f"{original_filename}: {exc}")
    import_result = _intake_postal_scan_pdf_paths(
        source_record=source_record,
        batch=batch,
        year=year,
        pdf_paths=saved_paths,
    )
    return PostalScanUploadResult(
        uploaded_count=uploaded_count,
        imported_count=import_result.imported_count,
        skipped_count=skipped_count + import_result.skipped_count,
        skipped_messages=skipped_messages,
        error_messages=error_messages + import_result.error_messages,
    )


def _intake_postal_scan_pdf_paths(
    *,
    source_record: LegacySource,
    batch: ImportBatch,
    year: int,
    pdf_paths: list[Path],
) -> PostalScanImportResult:
    imported_count = 0
    skipped_count = 0
    error_messages: list[str] = []
    candidate_population: _PostalScanCandidatePopulation | None = None
    for pdf_path in pdf_paths:
        try:
            pdf_sha256 = calculate_file_sha256(pdf_path)
            pdf_size = pdf_path.stat().st_size
            page_count = _pdf_page_count(pdf_path)
            statement_date = _extract_pdf_statement_date(pdf_path)
            slip_page_numbers = _postal_slip_page_numbers(page_count)
            existing_scans = {
                scan.page_number: scan
                for scan in AnnualMembershipFeePostalScan.objects.filter(
                    source=source_record,
                    year=year,
                    pdf_sha256=pdf_sha256,
                )
            }
            _update_existing_statement_dates(existing_scans.values(), statement_date)
            complete_page_numbers = {
                page_number
                for page_number, scan in existing_scans.items()
                if scan.page_image_storage_key
                and scan.crop_storage_key
                and scan.page_count == page_count
            }
            missing_page_numbers = [
                page_number
                for page_number in slip_page_numbers
                if page_number not in complete_page_numbers
            ]
            if not missing_page_numbers:
                skipped_count += len(slip_page_numbers)
                continue
            page_results = _create_page_artifacts_for_pdf(
                pdf_path,
                year=year,
                pdf_sha256=pdf_sha256,
                page_count=page_count,
                page_numbers=missing_page_numbers,
            )
            recognized_text = _default_recognition_text(pdf_path)
            if candidate_population is None:
                candidate_population = _build_postal_scan_candidate_population(
                    source_record=source_record,
                    year=year,
                )
            for page_result in page_results:
                existing_scan = existing_scans.get(page_result["page_number"])
                existing_status = (
                    existing_scan.status
                    if existing_scan is not None
                    else AnnualMembershipFeePostalScan.Status.PENDING
                )
                receipt_details = _extract_pdf_page_receipt_details(
                    pdf_path,
                    page_result["page_number"],
                )
                page_candidate_payload = _candidate_payload_with_receipt_details(
                    build_postal_scan_candidate_payload(
                        batch=batch,
                        source_record=source_record,
                        year=year,
                        query=recognized_text,
                        receipt_details=receipt_details,
                        candidate_population=candidate_population,
                    ),
                    receipt_details,
                )
                scan, created = AnnualMembershipFeePostalScan.objects.update_or_create(
                    source=source_record,
                    year=year,
                    pdf_sha256=pdf_sha256,
                    page_number=page_result["page_number"],
                    defaults={
                        "status": existing_status,
                        "pdf_storage_key": _storage_key_for_path(pdf_path),
                        "original_filename": pdf_path.name,
                        "pdf_size_bytes": pdf_size,
                        "page_count": page_count,
                        "statement_date": statement_date,
                        "page_image_storage_key": page_result.get("page_image_storage_key", ""),
                        "page_image_sha256": page_result.get("page_image_sha256", ""),
                        "crop_storage_key": page_result.get("crop_storage_key", ""),
                        "crop_sha256": page_result.get("crop_sha256", ""),
                        "crop_box": page_result.get("crop_box", {}),
                        "recognized_text": recognized_text,
                        "candidate_payload": page_candidate_payload,
                        "move_error": "",
                    },
                )
                if page_result.get("error"):
                    scan.status = AnnualMembershipFeePostalScan.Status.NEEDS_REVIEW
                    scan.move_error = str(page_result["error"])
                    scan.save(update_fields=["status", "move_error", "updated_at"])
                if created:
                    imported_count += 1
                else:
                    skipped_count += 1
        except Exception as exc:
            error_messages.append(f"{pdf_path.name}: {exc}")
    return PostalScanImportResult(
        imported_count=imported_count,
        skipped_count=skipped_count,
        error_messages=error_messages,
    )


def run_postal_scan_ocr_batch(
    *,
    source_record: LegacySource,
    batch: ImportBatch,
    year: int,
    client: PostalScanOcrClient | None = None,
    force: bool = False,
    limit: int | None = None,
    clear_stop: bool = True,
) -> PostalScanOcrBatchResult:
    lease = job_services.begin_run(year=year, clear_stop=clear_stop)
    if lease is None:
        return PostalScanOcrBatchResult(
            processed_count=0, skipped_count=0, error_messages=["AI OCRは既に実行中です。"],
        )
    try:
        return _run_postal_scan_ocr_batch_locked(
            source_record=source_record, batch=batch, year=year, client=client,
            force=force, limit=limit, clear_stop=False,
        )
    except Exception as exc:
        job_services.record_failure(year=year, error=exc)
        raise
    finally:
        job_services.finish_run(year=year, lease=lease)


def _run_postal_scan_ocr_batch_locked(
    *,
    source_record: LegacySource,
    batch: ImportBatch,
    year: int,
    client: PostalScanOcrClient | None = None,
    force: bool = False,
    limit: int | None = None,
    clear_stop: bool = True,
) -> PostalScanOcrBatchResult:
    client = client or PostalScanOcrClient()
    if not client.available:
        unavailable_reason = getattr(
            client,
            "unavailable_reason",
            "OPENAI_API_KEY が未設定です。",
        )
        _write_postal_scan_ocr_progress(
            year=year,
            progress=_postal_scan_ocr_progress_snapshot(
                state="error",
                total_count=0,
                completed_count=0,
                processed_count=0,
                skipped_count=0,
                error_messages=[unavailable_reason],
                message=unavailable_reason,
            ),
        )
        return PostalScanOcrBatchResult(
            processed_count=0,
            skipped_count=0,
            error_messages=[unavailable_reason],
        )
    processed_count = 0
    skipped_count = 0
    error_messages: list[str] = []
    stopped = False
    if clear_stop:
        _clear_postal_scan_ocr_stop(year=year)
    target_scans, skipped_count = _postal_scan_ocr_target_scans(
        source_record=source_record,
        year=year,
        force=force,
    )
    if limit is not None:
        target_scans = target_scans[:limit]
    total_count = len(target_scans)
    candidate_population: _PostalScanCandidatePopulation | None = None
    _write_postal_scan_ocr_progress(
        year=year,
        progress=_postal_scan_ocr_progress_snapshot(
            state="running",
            total_count=total_count,
            completed_count=0,
            processed_count=0,
            skipped_count=skipped_count,
            error_messages=[],
            message="AI OCRを実行中です。",
        ),
    )
    for index, scan in enumerate(target_scans, start=1):
        if _postal_scan_ocr_stop_requested(year=year):
            stopped = True
            break
        current_label = f"{scan.original_filename} p{scan.page_number}"
        _write_postal_scan_ocr_progress(
            year=year,
            progress=_postal_scan_ocr_progress_snapshot(
                state="running",
                total_count=total_count,
                completed_count=index - 1,
                processed_count=processed_count,
                skipped_count=skipped_count,
                error_messages=error_messages,
                current_label=current_label,
                current_scan_id=scan.id,
                message=f"{current_label} をAI OCR中です。",
            ),
        )
        try:
            if candidate_population is None:
                candidate_population = _build_postal_scan_candidate_population(
                    source_record=source_record,
                    year=year,
                )
            crop_path = postal_scan_file_path(scan, kind="crop")
            ocr_payload = client.recognize_crop(crop_path)
            recognized_text = _recognized_text_from_ocr_payload(ocr_payload)
            receipt_details = _postal_scan_receipt_details(scan)
            existing_reasoning_runs = list(
                (scan.candidate_payload or {}).get("ai_reasoning_runs") or []
            )
            existing_payload = dict(scan.candidate_payload or {})
            scan.recognized_text = recognized_text
            scan.candidate_payload = _candidate_payload_with_receipt_details(
                build_postal_scan_candidate_payload(
                    batch=batch,
                    source_record=source_record,
                    year=year,
                    query=recognized_text,
                    ocr_payload=ocr_payload,
                    receipt_details=receipt_details,
                    candidate_population=candidate_population,
                ),
                receipt_details,
            )
            if existing_reasoning_runs:
                scan.candidate_payload["ai_reasoning_runs"] = existing_reasoning_runs[-10:]
            for metadata_key in (
                "unknown_payment",
                "revision_history",
                pdf_move_services.PDF_MOVE_PENDING_SOURCE_KEY,
            ):
                if metadata_key in existing_payload:
                    scan.candidate_payload[metadata_key] = existing_payload[metadata_key]
            if scan.status == AnnualMembershipFeePostalScan.Status.PENDING:
                scan.status = AnnualMembershipFeePostalScan.Status.NEEDS_REVIEW
            scan.move_error = ""
            scan.save(
                update_fields=[
                    "recognized_text",
                    "candidate_payload",
                    "status",
                    "move_error",
                    "updated_at",
                ]
            )
            processed_count += 1
        except Exception as exc:
            error_messages.append(f"{scan.original_filename} p{scan.page_number}: {exc}")
        _write_postal_scan_ocr_progress(
            year=year,
            progress=_postal_scan_ocr_progress_snapshot(
                state="running",
                total_count=total_count,
                completed_count=index,
                processed_count=processed_count,
                skipped_count=skipped_count,
                error_messages=error_messages,
                current_label=current_label,
                current_scan_id=scan.id,
                message=f"{index} / {total_count} 件を確認しました。",
            ),
        )
    if stopped:
        _clear_postal_scan_ocr_stop(year=year)
    final_state = "stopped" if stopped else "completed"
    if total_count == 0:
        final_message = "AI OCR対象はありません。未OCRのscanがないか、切り抜きがありません。"
    else:
        final_message = (
            f"{processed_count}件をAI OCRして停止しました。"
            if stopped
            else f"{processed_count}件をAI OCRしました。"
        )
    _write_postal_scan_ocr_progress(
        year=year,
        progress=_postal_scan_ocr_progress_snapshot(
            state=final_state,
            total_count=total_count,
            completed_count=min(processed_count + len(error_messages), total_count),
            processed_count=processed_count,
            skipped_count=skipped_count,
            error_messages=error_messages,
            message=final_message,
        ),
    )
    return PostalScanOcrBatchResult(
        processed_count=processed_count,
        skipped_count=skipped_count,
        error_messages=error_messages,
        stopped=stopped,
    )


def start_postal_scan_ocr_batch(
    *,
    source_record: LegacySource,
    batch: ImportBatch,
    year: int,
    force: bool = False,
) -> PostalScanOcrStartResult:
    lease = job_services.begin_run(year=year)
    if lease is None:
        return PostalScanOcrStartResult(
            started=False, message="AI OCRは既に実行中です。",
            progress=read_postal_scan_ocr_progress(year=year),
        )
    transferred = False
    try:
        client = PostalScanOcrClient()
        if not client.available:
            result = _run_postal_scan_ocr_batch_locked(
                source_record=source_record, batch=batch, year=year, client=client, force=force,
            )
            return PostalScanOcrStartResult(
                started=False,
                message=result.error_messages[0] if result.error_messages else "AI OCRを開始できませんでした。",
                progress=read_postal_scan_ocr_progress(year=year),
            )
        target_scans, skipped_count = _postal_scan_ocr_target_scans(
            source_record=source_record, year=year, force=force,
        )
        progress = _postal_scan_ocr_progress_snapshot(
            state="running", total_count=len(target_scans), skipped_count=skipped_count,
            message="AI OCRを開始しました。",
        )
        _write_postal_scan_ocr_progress(year=year, progress=progress)
        _start_postal_scan_ocr_background_thread(
            source_record_pk=source_record.pk, batch_pk=batch.pk, year=year, force=force,
            lease=lease,
        )
        transferred = True
        return PostalScanOcrStartResult(started=True, message="AI OCRを開始しました。", progress=progress)
    except Exception as exc:
        job_services.record_failure(year=year, error=exc)
        return PostalScanOcrStartResult(
            started=False, message=f"AI OCRを開始できませんでした: {exc}",
            progress=read_postal_scan_ocr_progress(year=year),
        )
    finally:
        if not transferred:
            job_services.finish_run(year=year, lease=lease)


def request_postal_scan_ocr_stop(*, year: int) -> None:
    job_services.request_stop(year=year)


def read_postal_scan_ocr_progress(*, year: int) -> dict:
    return job_services.read_progress(year=year)


def update_postal_scan_search_candidates(
    *,
    scan: AnnualMembershipFeePostalScan,
    batch: ImportBatch,
    source_record: LegacySource,
    query: str,
) -> None:
    existing_payload = dict(scan.candidate_payload or {})
    ocr_payload = (scan.candidate_payload or {}).get("ocr") or {}
    receipt_details = _postal_scan_receipt_details(scan)
    handling_office_name = str(receipt_details.get("handling_office_name") or "")
    allow_handling_office_hint = not (query or "").strip() or (
        _normalize_search_text(query) == _normalize_search_text(handling_office_name)
    )
    refreshed_payload = _candidate_payload_with_receipt_details(
        build_postal_scan_candidate_payload(
            batch=batch,
            source_record=source_record,
            year=scan.year,
            query=query,
            ocr_payload=ocr_payload,
            receipt_details=receipt_details,
            allow_handling_office_hint=allow_handling_office_hint,
        ),
        receipt_details,
    )
    for metadata_key in (
        "unknown_payment",
        "revision_history",
        "ai_reasoning_runs",
        pdf_move_services.PDF_MOVE_PENDING_SOURCE_KEY,
    ):
        if metadata_key in existing_payload:
            refreshed_payload[metadata_key] = existing_payload[metadata_key]
    scan.candidate_payload = refreshed_payload
    scan.save(update_fields=["candidate_payload", "updated_at"])


def save_postal_scan_candidate_phone(
    *,
    source_record: LegacySource,
    batch: ImportBatch,
    selected_household_id: str,
    phone: str,
    phone_target: str,
    actor_label: str = "",
) -> PostalScanPhoneSaveResult:
    del batch
    cleaned_phone = (phone or "").strip()
    if not cleaned_phone:
        return PostalScanPhoneSaveResult(
            success=False, message="保存する電話番号を入力してください。"
        )
    target = phone_target if phone_target in {"phone", "mobile", "mailing_phone"} else "phone"
    target_label = {
        "phone": "電話",
        "mobile": "携帯",
        "mailing_phone": "送付先電話",
    }[target]
    household = (
        _active_canonical_households(source_id=source_record.source_id)
        .select_related("head_person")
        .filter(
            household_uid=selected_household_id,
        )
        .first()
    )
    if household is None:
        return PostalScanPhoneSaveResult(success=False, message="候補の家が見つかりません。")

    with transaction.atomic():
        household = Household.objects.select_for_update().get(pk=household.pk)
        before_data = _serialize_household_record(household)
        if target in {"phone", "mobile"}:
            current_value = (getattr(household, target) or "").strip()
            if current_value:
                return PostalScanPhoneSaveResult(
                    success=False,
                    message=f"この家には既に{target_label}が入っています。",
                )
            setattr(household, target, cleaned_phone)
            raw_record = dict(household.raw_record or {})
            raw_record["電話" if target == "phone" else "携帯"] = cleaned_phone
            household.raw_record = raw_record
            household.save(update_fields=[target, "raw_record", "updated_at"])
        else:
            profile, _created = HouseholdProfile.objects.select_for_update().get_or_create(
                source=source_record,
                household_uid=household.household_uid,
            )
            if (profile.mailing_phone or "").strip():
                return PostalScanPhoneSaveResult(
                    success=False,
                    message="この家には既に送付先電話が入っています。",
                )
            profile.mailing_phone = cleaned_phone
            profile.save(update_fields=["mailing_phone", "updated_at"])
        household = Household.objects.select_related("head_person").get(pk=household.pk)
        log_entry = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.HOUSEHOLD,
            record=household,
            before_data=before_data,
            after_data=_serialize_household_record(household),
            editor_label=actor_label,
            change_note=f"郵便振込PDF照合で{target_label}を補記",
        )
    return PostalScanPhoneSaveResult(
        success=True,
        message=record_action_message_text(
            log_entry, f"{household} の{target_label}を保存しました。"
        ),
    )


def save_postal_scan_candidate_contact(
    *,
    source_record: LegacySource,
    batch: ImportBatch,
    selected_household_id: str,
    postal_code: str,
    address_line1: str,
    address_line2: str,
    address_line3: str,
    phone: str,
    mobile: str,
    mailing_phone: str,
    actor_label: str = "",
) -> PostalScanContactSaveResult:
    del batch
    household = (
        _active_canonical_households(source_id=source_record.source_id)
        .select_related("head_person")
        .filter(
            household_uid=selected_household_id,
        )
        .first()
    )
    if household is None:
        return PostalScanContactSaveResult(success=False, message="候補の家が見つかりません。")

    cleaned_household_values = {
        "postal_code": (postal_code or "").strip(),
        "address_line1": (address_line1 or "").strip(),
        "address_line2": (address_line2 or "").strip(),
        "address_line3": (address_line3 or "").strip(),
        "phone": (phone or "").strip(),
        "mobile": (mobile or "").strip(),
    }
    cleaned_mailing_phone = (mailing_phone or "").strip()

    with transaction.atomic():
        household = Household.objects.select_for_update().get(pk=household.pk)
        before_data = _serialize_household_record(household)
        raw_record = dict(household.raw_record or {})
        update_fields: list[str] = []
        raw_record_keys = {
            "postal_code": "〒",
            "address_line1": "住所1",
            "address_line2": "住所2",
            "address_line3": "住所3",
            "phone": "電話",
            "mobile": "携帯",
        }
        for field_name, new_value in cleaned_household_values.items():
            if (getattr(household, field_name) or "") == new_value:
                continue
            setattr(household, field_name, new_value)
            raw_record[raw_record_keys[field_name]] = new_value
            update_fields.append(field_name)
        if update_fields:
            household.raw_record = raw_record
            household.save(update_fields=[*update_fields, "raw_record", "updated_at"])

        profile = (
            HouseholdProfile.objects.select_for_update()
            .filter(
                source=source_record,
                household_uid=household.household_uid,
            )
            .first()
        )
        if profile is not None and (profile.mailing_phone or "") != cleaned_mailing_phone:
            profile.mailing_phone = cleaned_mailing_phone
            profile.save(update_fields=["mailing_phone", "updated_at"])
        elif profile is None and cleaned_mailing_phone:
            HouseholdProfile.objects.create(
                source=source_record,
                household_uid=household.household_uid,
                mailing_phone=cleaned_mailing_phone,
            )

        household = Household.objects.select_related("head_person").get(pk=household.pk)
        log_entry = _create_record_edit_log(
            record_type=RecordEditLog.RecordType.HOUSEHOLD,
            record=household,
            before_data=before_data,
            after_data=_serialize_household_record(household),
            editor_label=actor_label,
            change_note="郵便振込PDF照合で住所・電話を修正",
        )
    return PostalScanContactSaveResult(
        success=True,
        message=record_action_message_text(log_entry, f"{household} の住所・電話を保存しました。"),
    )


def build_postal_scan_candidate_payload(
    *,
    batch: ImportBatch,
    source_record: LegacySource,
    year: int | None = None,
    query: str,
    ocr_payload: dict | None = None,
    receipt_details: dict | None = None,
    allow_handling_office_hint: bool = True,
    limit: int = matching_services.POSTAL_SCAN_MAX_CANDIDATES,
    candidate_population: _PostalScanCandidatePopulation | None = None,
) -> dict:
    del batch
    ocr_payload = _normalize_ocr_payload(ocr_payload) if ocr_payload else {}
    cleaned_query = (query or "").strip()
    normalized_query = _normalize_search_text(cleaned_query)
    query_terms = matching_services.query_search_terms(cleaned_query)
    normalized_ocr_terms = _ocr_search_terms(ocr_payload)
    ocr_phone_numbers = _normalize_phone_numbers(ocr_payload.get("phone") if ocr_payload else "")
    ocr_address = str(ocr_payload.get("address") or "") if ocr_payload else ""
    ocr_postal_code = _normalize_postal_code(ocr_address)
    normalized_ocr_address = _normalize_search_text(ocr_address)
    handling_office_name = str((receipt_details or {}).get("handling_office_name") or "").strip()
    if (
        not normalized_query
        and not normalized_ocr_terms
        and not ocr_phone_numbers
        and not normalized_ocr_address
        and not handling_office_name
    ):
        return {"query": cleaned_query, "ocr": ocr_payload, "candidates": []}
    population = candidate_population or _build_postal_scan_candidate_population(
        source_record=source_record,
        year=year,
    )
    candidates = []
    for household in population.households:
        profile = population.profiles.get(household.household_uid)
        if not _postal_scan_candidate_profile_is_relevant(profile):
            continue
        head_name = _household_display_head_name(household)
        head_kana = _household_display_head_name_kana(household)
        score, match_reasons = _candidate_score_for_scan(
            normalized_query=normalized_query,
            ocr_terms=normalized_ocr_terms,
            ocr_phone_numbers=ocr_phone_numbers,
            ocr_address=ocr_address,
            ocr_postal_code=ocr_postal_code,
            normalized_ocr_address=normalized_ocr_address,
            household=household,
            profile=profile,
            head_name=head_name,
            head_kana=head_kana,
            household_member_names=population.member_names_by_household_pk.get(household.pk, []),
            query_terms=query_terms,
        )
        if score <= 0:
            continue
        candidates.append(
            _postal_scan_candidate_record(
                household=household,
                profile=profile,
                head_name=head_name,
                head_kana=head_kana,
                score=score,
                match_reasons=match_reasons,
            )
        )
    candidate_notice = ""
    handling_office_evidence = None
    if not candidates and handling_office_name and allow_handling_office_hint:
        handling_candidates = []
        evidence_rows = []
        for household in population.households:
            profile = population.profiles.get(household.household_uid)
            if not matching_services.handling_office_matches_candidate_address(
                handling_office_name=handling_office_name,
                household=household,
                profile=profile,
            ):
                continue
            head_name = _household_display_head_name(household)
            display_fields = _postal_scan_candidate_display_fields(
                household=household,
                profile=profile,
                head_name=head_name,
                head_kana=_household_display_head_name_kana(household),
            )
            if household.household_uid in population.paid_household_uids:
                payment = population.payments_by_household_uid.get(household.household_uid)
                paid_details = []
                if payment is not None and payment.received_on:
                    paid_details.append(payment.received_on.isoformat())
                if payment is not None and payment.amount is not None:
                    paid_details.append(f"{payment.amount:g}円")
                paid_suffix = f"（{' / '.join(paid_details)}）" if paid_details else ""
                evidence_rows.append(
                    {
                        "legacy_household_id": household.household_uid,
                        "household_name": display_fields["household_name"],
                        "address": display_fields["address"],
                        "delivery_method_label": display_fields["delivery_method_label"],
                        "status": "paid",
                        "status_label": f"{year}年度は入金済み{paid_suffix}",
                    }
                )
                continue
            exclusion_reason = _annual_membership_fee_exclusion_reason(
                household=household,
                profile=profile,
            )
            can_receive_payment, receipt_warning = _postal_scan_receipt_policy(
                profile=profile,
                exclusion_reason=exclusion_reason,
            )
            if not can_receive_payment:
                evidence_rows.append(
                    {
                        "legacy_household_id": household.household_uid,
                        "household_name": display_fields["household_name"],
                        "address": display_fields["address"],
                        "delivery_method_label": display_fields["delivery_method_label"],
                        "status": "excluded",
                        "status_label": f"請求対象外: {exclusion_reason}",
                    }
                )
                continue
            head_kana = _household_display_head_name_kana(household)
            evidence_rows.append(
                {
                    "legacy_household_id": household.household_uid,
                    "household_name": display_fields["household_name"],
                    "address": display_fields["address"],
                    "delivery_method_label": display_fields["delivery_method_label"],
                    "status": "exception_eligible" if receipt_warning else "eligible",
                    "status_label": (
                        "未納・案内不要（実入金は受領可能）"
                        if receipt_warning
                        else "未納・請求対象"
                    ),
                }
            )
            handling_candidates.append(
                _postal_scan_candidate_record(
                    household=household,
                    profile=profile,
                    head_name=head_name,
                    head_kana=head_kana,
                    score=55,
                    match_reasons=[f"取扱店所在地による参考候補（{handling_office_name}）"],
                    candidate_source="handling_office",
                )
            )
        handling_office_evidence = {
            "handling_office_name": handling_office_name,
            "handling_office_code": str((receipt_details or {}).get("handling_office_code") or ""),
            "address_match_count": len(evidence_rows),
            "rows": evidence_rows,
            "note": "取扱店は住所の証明ではないため、参考情報として人が確認します。",
        }
        if len(handling_candidates) <= matching_services.POSTAL_SCAN_MAX_CANDIDATES:
            candidates = handling_candidates
        else:
            candidate_notice = (
                f"取扱店「{handling_office_name}」と住所が一致する未納世帯が"
                f"{len(handling_candidates)}件あるため、参考候補を表示していません。"
            )
    candidates.sort(
        key=lambda item: (-int(item["score"]), item["household_name"], item["legacy_household_id"])
    )
    payload = {
        "query": cleaned_query,
        "ocr": ocr_payload,
        "candidates": matching_services.select_postal_scan_candidates(
            candidates,
            limit=limit,
        ),
    }
    if candidate_notice:
        payload["candidate_notice"] = candidate_notice
    if handling_office_evidence:
        payload["handling_office_evidence"] = handling_office_evidence
    return payload


def _postal_scan_candidate_record(
    *,
    household: Household,
    profile: HouseholdProfile | None,
    head_name: str,
    head_kana: str,
    score: int,
    match_reasons: list[str],
    candidate_source: str = "matching",
) -> dict:
    exclusion_reason = _annual_membership_fee_exclusion_reason(
        household=household,
        profile=profile,
    )
    can_receive_payment, receipt_warning = _postal_scan_receipt_policy(
        profile=profile,
        exclusion_reason=exclusion_reason,
    )
    return {
        "legacy_household_id": household.household_uid,
        **_postal_scan_candidate_display_fields(
            household=household,
            profile=profile,
            head_name=head_name,
            head_kana=head_kana,
        ),
        "score": score,
        "match_reasons": match_reasons,
        "candidate_source": candidate_source,
        "is_billable": not bool(exclusion_reason),
        "billing_note": exclusion_reason,
        "can_receive_payment": can_receive_payment,
        "receipt_warning": receipt_warning,
    }


def _postal_scan_receipt_policy(
    *,
    profile: HouseholdProfile | None,
    exclusion_reason: str,
) -> tuple[bool, str]:
    return payment_services.postal_scan_receipt_policy(
        profile=profile,
        exclusion_reason=exclusion_reason,
    )


_POSTAL_SCAN_AI_ASSESSMENT_LABELS = {
    "most_likely": "最も可能性が高い",
    "possible": "可能性あり",
    "unlikely": "可能性は低い",
    "ineligible": "受領候補にできない",
}

_POSTAL_SCAN_REASONING_FACT_LABELS = {
    "address_matches_handling_office": "取扱店名と住所地域の一致",
    "already_paid": "当年度の入金状況",
    "billable": "通常請求対象かどうか",
    "can_receive_payment": "この振込を受領できるか",
    "exclusion_category": "請求対象外の理由",
    "delivery_method": "送付区分",
    "deterministic_match_score": "既存ルールによる一致度",
    "deterministic_match_signals": "既存照合で一致した情報",
}

_POSTAL_SCAN_REASONING_BOOLEAN_LABELS = {
    "address_matches_handling_office": {
        True: "取扱店名と住所地域が一致",
        False: "取扱店名と住所地域は一致しない",
    },
    "already_paid": {
        True: "当年度入金済み",
        False: "当年度未納",
    },
    "billable": {
        True: "通常請求対象",
        False: "通常請求対象外",
    },
    "can_receive_payment": {
        True: "受領可能",
        False: "受領不可",
    },
}

_POSTAL_SCAN_REASONING_TECHNICAL_LABELS = {
    "case.handling_office_code_available": "取扱店コードが確認できたか",
    "case.handling_office_available": "取扱店名が確認できたか",
    "case.address_was_read": "住所が読み取れたか",
    "case.phone_was_read": "電話番号が読み取れたか",
    "case.name_was_read": "氏名が読み取れたか",
    "case.ocr_confidence": "OCR信頼度",
    "case.fiscal_year": "対象年度",
    "handling_office_code_available": "取扱店コードが確認できたか",
    "handling_office_available": "取扱店名が確認できたか",
    "address_was_read": "住所が読み取れたか",
    "phone_was_read": "電話番号が読み取れたか",
    "name_was_read": "氏名が読み取れたか",
    "ocr_confidence": "OCR信頼度",
    "fiscal_year": "対象年度",
    "address_matches_handling_office": "取扱店名と住所地域の一致",
    "deterministic_match_signals": "既存照合で一致した情報",
    "deterministic_match_score": "既存ルールによる一致度",
    "handling_office_address_match": "取扱店名と住所地域の一致",
    "current_family_name_match": "現行家族名との一致",
    "household_head_name_match": "戸主名との一致",
    "manual_search_match": "手動検索条件との一致",
    "mailing_name_match": "別送付先名との一致",
    "postal_code_match": "郵便番号の一致",
    "can_receive_payment": "この振込を受領できるか",
    "exclusion_category": "請求対象外の理由",
    "delivery_method": "送付区分",
    "already_paid": "当年度の入金状況",
    "address_match": "住所の一致",
    "phone_match": "電話番号の一致",
    "delivery_unset": "送付区分未設定",
    "district_unset": "地区未設定",
    "womens_association": "婦人会対象外",
    "no_notice": "案内不要",
    "billable": "通常請求対象かどうか",
    "most_likely": "最も可能性が高い",
    "ineligible": "受領候補にできない",
    "unlikely": "可能性は低い",
    "possible": "可能性あり",
    "district": "地区配布",
    "postal": "郵送",
    "unset": "未設定",
    "other": "その他",
    "none": "該当なし",
    "false": "いいえ",
    "true": "はい",
}

_POSTAL_SCAN_REASONING_CANDIDATE_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<candidate_key>c\d+)"
    r"(?:\.(?P<fact_key>[A-Za-z0-9_]+))?"
    r"(?:\s*=\s*(?P<boolean_value>true|false))?"
    r"(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def _postal_scan_reasoning_candidate_names(
    reasoning: dict[str, Any],
    local_candidates: dict[str, dict[str, Any]] | None = None,
) -> dict[str, str]:
    names = {}
    for candidate_key, candidate in (local_candidates or {}).items():
        household_name = str(candidate.get("household_name") or "").strip()
        if household_name:
            names[str(candidate_key).strip().lower()] = household_name
    for assessment in list(reasoning.get("candidate_assessments") or []):
        if not isinstance(assessment, dict):
            continue
        candidate_key = str(assessment.get("candidate_key") or "").strip().lower()
        household_name = str(assessment.get("household_name") or "").strip()
        if candidate_key and household_name:
            names[candidate_key] = household_name
    return names


def _humanize_postal_scan_reasoning_text(
    value: Any,
    *,
    candidate_names: dict[str, str],
    own_candidate_key: str = "",
) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    own_candidate_key = own_candidate_key.strip().lower()

    def replace_candidate_reference(match: re.Match[str]) -> str:
        candidate_key = match.group("candidate_key").lower()
        fact_key = str(match.group("fact_key") or "").lower()
        boolean_value = str(match.group("boolean_value") or "").lower()
        candidate_label = (
            "この候補"
            if own_candidate_key and candidate_key == own_candidate_key
            else candidate_names.get(candidate_key, "候補")
        )
        if not fact_key:
            return candidate_label
        if boolean_value:
            boolean_label = _POSTAL_SCAN_REASONING_BOOLEAN_LABELS.get(fact_key, {}).get(
                boolean_value == "true"
            )
            if boolean_label:
                return f"{candidate_label}は{boolean_label}"
        fact_label = _POSTAL_SCAN_REASONING_FACT_LABELS.get(fact_key, "比較情報")
        return f"{candidate_label}の{fact_label}"

    text = _POSTAL_SCAN_REASONING_CANDIDATE_REFERENCE_RE.sub(
        replace_candidate_reference,
        text,
    )
    text = re.sub(
        r"(?<![A-Za-z0-9_])can_receive_payment\s*=\s*false(?![A-Za-z0-9_])",
        "受領不可",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?<![A-Za-z0-9_])can_receive_payment\s*=\s*true(?![A-Za-z0-9_])",
        "受領可能",
        text,
        flags=re.IGNORECASE,
    )
    for technical_name, japanese_label in sorted(
        _POSTAL_SCAN_REASONING_TECHNICAL_LABELS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        text = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(technical_name)}(?![A-Za-z0-9_])",
            japanese_label,
            text,
            flags=re.IGNORECASE,
        )
    for source_text, japanese_text in (
        ("決定的照合スコア", "既存ルールによる一致度"),
        ("決定的照合", "既存照合"),
        ("照合シグナル", "一致した情報"),
        ("取扱店住所一致", "取扱店名と住所地域の一致"),
        ("受入可能", "受領可能"),
        ("受入不可", "受領不可"),
        ("既入金", "入金済み"),
        ("未入金", "未納"),
    ):
        text = text.replace(source_text, japanese_text)
    return text


def _postal_scan_reasoning_for_display(
    reasoning: dict[str, Any],
    local_candidates: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    display_reasoning = dict(reasoning)
    candidate_names = _postal_scan_reasoning_candidate_names(reasoning, local_candidates)
    display_reasoning["summary"] = _humanize_postal_scan_reasoning_text(
        reasoning.get("summary"),
        candidate_names=candidate_names,
    )
    display_steps = []
    for step in list(reasoning.get("reasoning_steps") or []):
        if not isinstance(step, dict):
            continue
        display_step = dict(step)
        display_step["interpretation"] = _humanize_postal_scan_reasoning_text(
            step.get("interpretation"),
            candidate_names=candidate_names,
        )
        display_steps.append(display_step)
    display_reasoning["reasoning_steps"] = display_steps
    display_reasoning["reasoning_points"] = [
        step["interpretation"] for step in display_steps if step.get("interpretation")
    ]
    display_assessments = []
    for assessment in list(reasoning.get("candidate_assessments") or []):
        if not isinstance(assessment, dict):
            continue
        display_assessment = dict(assessment)
        candidate_key = str(assessment.get("candidate_key") or "").strip()
        display_assessment["reason"] = _humanize_postal_scan_reasoning_text(
            assessment.get("reason"),
            candidate_names=candidate_names,
            own_candidate_key=candidate_key,
        )
        display_assessments.append(display_assessment)
    display_reasoning["candidate_assessments"] = display_assessments
    display_reasoning["uncertainties"] = [
        _humanize_postal_scan_reasoning_text(
            uncertainty,
            candidate_names=candidate_names,
        )
        for uncertainty in list(reasoning.get("uncertainties") or [])
        if str(uncertainty or "").strip()
    ]
    return display_reasoning


def _postal_scan_reasoning_match_signals(candidate: dict | None) -> list[str]:
    reasons = list((candidate or {}).get("match_reasons") or [])
    signals = []
    for reason in reasons:
        reason_text = str(reason or "")
        if "検索語一致" in reason_text:
            signals.append("manual_search_match")
        if "家族氏名" in reason_text:
            signals.append("current_family_name_match")
        elif "送付先氏名" in reason_text:
            signals.append("mailing_name_match")
        elif "氏名" in reason_text:
            signals.append("household_head_name_match")
        if "電話" in reason_text:
            signals.append("phone_match")
        if "郵便番号" in reason_text:
            signals.append("postal_code_match")
        if "住所" in reason_text and "取扱店" not in reason_text:
            signals.append("address_match")
        if "取扱店" in reason_text:
            signals.append("handling_office_address_match")
    return matching_services.dedupe_text_list(signals)


def _postal_scan_reasoning_exclusion_category(exclusion_reason: str) -> str:
    if not exclusion_reason:
        return "none"
    if exclusion_reason == ANNUAL_MEMBERSHIP_FEE_NO_NOTICE_EXCLUSION_REASON:
        return "no_notice"
    if "送付区分が未設定" in exclusion_reason:
        return "delivery_unset"
    if "地区が未設定" in exclusion_reason:
        return "district_unset"
    if "婦人会" in exclusion_reason:
        return "womens_association"
    return "other"


def _postal_scan_reasoning_candidate_sort_key(household_uid: str) -> tuple[int, int | str]:
    cleaned = str(household_uid or "").strip()
    if cleaned.isdigit():
        return (0, int(cleaned))
    return (1, cleaned)


def _build_postal_scan_reasoning_evidence(
    *,
    scan: AnnualMembershipFeePostalScan,
    payload: dict,
    candidate_population: _PostalScanCandidatePopulation,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    receipt_details = payload.get("receipt_details") or {}
    ocr_payload = _normalize_ocr_payload(payload.get("ocr") or {})
    handling_office_name = str(receipt_details.get("handling_office_name") or "").strip()
    evidence_rows = list((payload.get("handling_office_evidence") or {}).get("rows") or [])
    evidence_uids = {
        str(row.get("legacy_household_id") or "").strip()
        for row in evidence_rows
        if str(row.get("legacy_household_id") or "").strip()
    }
    candidates_by_uid = {
        str(candidate.get("legacy_household_id") or "").strip(): candidate
        for candidate in list(payload.get("candidates") or [])
        if str(candidate.get("legacy_household_id") or "").strip()
    }
    candidate_uids = evidence_uids | set(candidates_by_uid)
    households_by_uid = {
        household.household_uid: household
        for household in candidate_population.households
        if household.household_uid in candidate_uids
    }
    case_facts = [
        {"key": "case.fiscal_year", "value": scan.year},
        {"key": "case.name_was_read", "value": bool(ocr_payload.get("name"))},
        {"key": "case.address_was_read", "value": bool(ocr_payload.get("address"))},
        {"key": "case.phone_was_read", "value": bool(ocr_payload.get("phone"))},
        {
            "key": "case.ocr_confidence",
            "value": float(ocr_payload.get("confidence") or 0),
        },
        {
            "key": "case.handling_office_available",
            "value": bool(handling_office_name),
        },
        {
            "key": "case.handling_office_code_available",
            "value": bool(receipt_details.get("handling_office_code")),
        },
    ]
    api_candidates = []
    local_candidates: dict[str, dict[str, Any]] = {}
    for index, household_uid in enumerate(
        sorted(households_by_uid, key=_postal_scan_reasoning_candidate_sort_key),
        start=1,
    ):
        household = households_by_uid[household_uid]
        profile = candidate_population.profiles.get(household_uid)
        payment = candidate_population.payments_by_household_uid.get(household_uid)
        exclusion_reason = _annual_membership_fee_exclusion_reason(
            household=household,
            profile=profile,
        )
        can_receive_payment, receipt_warning = _postal_scan_receipt_policy(
            profile=profile,
            exclusion_reason=exclusion_reason,
        )
        candidate = candidates_by_uid.get(household_uid)
        try:
            deterministic_score = int((candidate or {}).get("score") or 0)
        except (TypeError, ValueError):
            deterministic_score = 0
        address_matches_handling_office = bool(
            handling_office_name
            and matching_services.handling_office_matches_candidate_address(
                handling_office_name=handling_office_name,
                household=household,
                profile=profile,
            )
        )
        candidate_key = f"c{index}"
        candidate_facts = [
            {
                "key": f"{candidate_key}.address_matches_handling_office",
                "value": address_matches_handling_office,
            },
            {
                "key": f"{candidate_key}.already_paid",
                "value": payment is not None,
            },
            {
                "key": f"{candidate_key}.billable",
                "value": not bool(exclusion_reason),
            },
            {
                "key": f"{candidate_key}.can_receive_payment",
                "value": can_receive_payment,
            },
            {
                "key": f"{candidate_key}.exclusion_category",
                "value": _postal_scan_reasoning_exclusion_category(exclusion_reason),
            },
            {
                "key": f"{candidate_key}.delivery_method",
                "value": (profile.delivery_method or "unset") if profile is not None else "unset",
            },
            {
                "key": f"{candidate_key}.deterministic_match_score",
                "value": deterministic_score,
            },
            {
                "key": f"{candidate_key}.deterministic_match_signals",
                "value": _postal_scan_reasoning_match_signals(candidate),
            },
        ]
        api_candidates.append(
            {
                "candidate_key": candidate_key,
                "facts": candidate_facts,
            }
        )
        display_fields = _postal_scan_candidate_display_fields(
            household=household,
            profile=profile,
            head_name=_household_display_head_name(household),
            head_kana=_household_display_head_name_kana(household),
        )
        if payment is not None:
            status_label = f"{scan.year}年度は入金済み"
        elif receipt_warning:
            status_label = "未納・案内不要（実入金は受領可能）"
        elif exclusion_reason:
            status_label = f"請求対象外: {exclusion_reason}"
        else:
            status_label = "未納・請求対象"
        local_candidates[candidate_key] = {
            "household_uid": household_uid,
            "household_name": display_fields["household_name"],
            "status_label": status_label,
            "already_paid": payment is not None,
            "can_receive_payment": can_receive_payment,
        }
    return {
        "case_facts": case_facts,
        "candidates": api_candidates,
    }, local_candidates


def _postal_scan_reasoning_input_digest(evidence: dict[str, Any]) -> str:
    canonical_json = json.dumps(
        evidence,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _postal_scan_reasoning_candidate_identity_digest(
    candidates: dict[str, dict[str, Any]],
) -> str:
    identities = [
        {
            "candidate_key": str(candidate_key),
            "household_uid": str(candidate.get("household_uid") or ""),
        }
        for candidate_key, candidate in sorted(candidates.items())
    ]
    canonical_json = json.dumps(
        identities,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _saved_postal_scan_reasoning_candidate_identity_digest(
    reasoning: dict[str, Any],
) -> str:
    saved_digest = str(reasoning.get("candidate_identity_digest") or "").strip()
    if saved_digest:
        return saved_digest
    saved_candidates = {}
    for assessment in list(reasoning.get("candidate_assessments") or []):
        if not isinstance(assessment, dict):
            continue
        candidate_key = str(assessment.get("candidate_key") or "").strip()
        household_uid = str(assessment.get("household_uid") or "").strip()
        if candidate_key and household_uid:
            saved_candidates[candidate_key] = {"household_uid": household_uid}
    if not saved_candidates:
        return ""
    return _postal_scan_reasoning_candidate_identity_digest(saved_candidates)


def _postal_scan_reasoning_allowed_fact_keys(evidence: dict[str, Any]) -> set[str]:
    return {
        str(fact.get("key") or "")
        for fact in [
            *list(evidence.get("case_facts") or []),
            *[
                fact
                for candidate in list(evidence.get("candidates") or [])
                for fact in list(candidate.get("facts") or [])
            ],
        ]
        if str(fact.get("key") or "")
    }


def _validated_postal_scan_reasoning(
    *,
    raw_result: dict[str, Any],
    evidence: dict[str, Any],
    local_candidates: dict[str, dict[str, Any]],
    actor_label: str,
) -> dict[str, Any]:
    allowed_fact_keys = _postal_scan_reasoning_allowed_fact_keys(evidence)
    reasoning_steps = []
    for step in list(raw_result.get("reasoning_steps") or []):
        if not isinstance(step, dict):
            continue
        fact_keys = [
            key
            for key in matching_services.dedupe_text_list(step.get("fact_keys") or [])
            if key in allowed_fact_keys
        ]
        interpretation = str(step.get("interpretation") or "").strip()
        if fact_keys and interpretation:
            reasoning_steps.append(
                {
                    "fact_keys": fact_keys,
                    "interpretation": interpretation,
                }
            )
    assessments_by_key = {}
    for assessment in list(raw_result.get("candidate_assessments") or []):
        if not isinstance(assessment, dict):
            continue
        candidate_key = str(assessment.get("candidate_key") or "").strip()
        assessment_code = str(assessment.get("assessment") or "").strip()
        reason = str(assessment.get("reason") or "").strip()
        if (
            candidate_key not in local_candidates
            or assessment_code not in _POSTAL_SCAN_AI_ASSESSMENT_LABELS
            or not reason
            or candidate_key in assessments_by_key
        ):
            continue
        assessments_by_key[candidate_key] = {
            "candidate_key": candidate_key,
            "assessment": assessment_code,
            "assessment_label": _POSTAL_SCAN_AI_ASSESSMENT_LABELS[assessment_code],
            "reason": reason,
        }
    candidate_assessments = []
    for candidate_key, local_candidate in local_candidates.items():
        assessment = assessments_by_key.get(candidate_key) or {
            "candidate_key": candidate_key,
            "assessment": "",
            "assessment_label": "AI個別評価なし",
            "reason": "AIからこの候補の個別評価が返りませんでした。",
        }
        candidate_assessments.append({**assessment, **local_candidate})

    recommended_key = str(raw_result.get("recommended_candidate_key") or "").strip()
    recommended_candidate = local_candidates.get(recommended_key)
    recommendation_valid = bool(
        recommended_candidate
        and not recommended_candidate["already_paid"]
        and recommended_candidate["can_receive_payment"]
    )
    uncertainties = list(raw_result.get("uncertainties") or [])
    if any(
        fact.get("key") == "case.handling_office_available" and fact.get("value") is True
        for fact in list(evidence.get("case_facts") or [])
    ):
        uncertainties.append("取扱店は振込人の住所を証明するものではありません。")
    uncertainties = matching_services.dedupe_text_list(uncertainties)
    recommended_assessment = assessments_by_key.get(recommended_key) if recommended_key else None
    if recommended_key and not recommendation_valid:
        uncertainties.append("AIの推薦先が現在の受領条件に合わないため、推薦を無効にしました。")
    elif recommended_key and (
        recommended_assessment is None or recommended_assessment.get("assessment") != "most_likely"
    ):
        recommendation_valid = False
        uncertainties.append("AIの推薦と候補別評価が一致しないため、推薦を無効にしました。")
    recommended_household_uid = (
        str(recommended_candidate["household_uid"])
        if recommendation_valid and recommended_candidate
        else ""
    )
    recommended_household_name = (
        str(recommended_candidate["household_name"])
        if recommendation_valid and recommended_candidate
        else ""
    )
    validated_reasoning = {
        "provider": "openai",
        "model": str(raw_result.get("model") or reasoning_services.POSTAL_SCAN_REASONING_MODEL),
        "processed_at": timezone.now().isoformat(),
        "processed_by": actor_label,
        "input_digest": _postal_scan_reasoning_input_digest(evidence),
        "candidate_identity_digest": _postal_scan_reasoning_candidate_identity_digest(
            local_candidates
        ),
        "input_facts": evidence,
        "recommended_candidate_key": recommended_key if recommendation_valid else "",
        "recommended_household_uid": recommended_household_uid,
        "recommended_household_name": recommended_household_name,
        "recommendation_valid": recommendation_valid,
        "confidence": float(raw_result.get("confidence") or 0),
        "summary": str(raw_result.get("summary") or "").strip(),
        "reasoning_steps": reasoning_steps,
        "reasoning_points": [step["interpretation"] for step in reasoning_steps],
        "candidate_assessments": candidate_assessments,
        "uncertainties": matching_services.dedupe_text_list(uncertainties),
        "needs_human_confirmation": True,
        "stale": False,
        "stale_message": "",
    }
    return _postal_scan_reasoning_for_display(validated_reasoning, local_candidates)


def _postal_scan_payload_for_reasoning(
    *,
    scan: AnnualMembershipFeePostalScan,
    batch: ImportBatch,
    source_record: LegacySource,
    candidate_population: _PostalScanCandidatePopulation,
) -> dict:
    existing_payload = dict(scan.candidate_payload or {})
    receipt_details = _postal_scan_receipt_details(scan)
    query = str(existing_payload.get("query") or "")
    handling_office_name = str(receipt_details.get("handling_office_name") or "")
    allow_handling_office_hint = (
        not query.strip()
        or _normalize_search_text(query) == _normalize_search_text(handling_office_name)
        or query.strip() == (scan.recognized_text or "").strip()
    )
    refreshed_payload = build_postal_scan_candidate_payload(
        batch=batch,
        source_record=source_record,
        year=scan.year,
        query=query,
        ocr_payload=existing_payload.get("ocr") or {},
        receipt_details=receipt_details,
        allow_handling_office_hint=allow_handling_office_hint,
        candidate_population=candidate_population,
    )
    refreshed_payload = _candidate_payload_with_receipt_details(
        refreshed_payload,
        receipt_details,
    )
    for metadata_key in (
        "unknown_payment",
        "revision_history",
        pdf_move_services.PDF_MOVE_PENDING_SOURCE_KEY,
    ):
        if metadata_key in existing_payload:
            refreshed_payload[metadata_key] = existing_payload[metadata_key]
    return refreshed_payload


def run_postal_scan_ai_reasoning(
    *,
    source_record: LegacySource,
    batch: ImportBatch,
    scan: AnnualMembershipFeePostalScan,
    year: int,
    actor_label: str = "",
    client: PostalScanReasoningClient | None = None,
) -> PostalScanReasoningRunResult:
    if scan.source_id != source_record.id or scan.year != year:
        return PostalScanReasoningRunResult(False, "この年度の郵便振込PDFではありません。")
    allowed_statuses = {
        AnnualMembershipFeePostalScan.Status.PENDING,
        AnnualMembershipFeePostalScan.Status.NEEDS_REVIEW,
    }
    if scan.status not in allowed_statuses or scan.payment_id:
        return PostalScanReasoningRunResult(False, "未確認のPDFだけAI推理を実行できます。")
    candidate_population = _build_postal_scan_candidate_population(
        source_record=source_record,
        year=year,
    )
    payload = _postal_scan_payload_for_reasoning(
        scan=scan,
        batch=batch,
        source_record=source_record,
        candidate_population=candidate_population,
    )
    evidence, local_candidates = _build_postal_scan_reasoning_evidence(
        scan=scan,
        payload=payload,
        candidate_population=candidate_population,
    )
    if not local_candidates:
        return PostalScanReasoningRunResult(
            False,
            "AIが比較できる候補がありません。取扱店や名前検索の根拠を確認してください。",
        )
    reasoning_client = client or PostalScanReasoningClient()
    try:
        raw_result = reasoning_client.reason(evidence)
    except PostalScanReasoningError as exc:
        return PostalScanReasoningRunResult(False, f"AI推理を実行できませんでした: {exc}")
    reasoning = _validated_postal_scan_reasoning(
        raw_result=raw_result,
        evidence=evidence,
        local_candidates=local_candidates,
        actor_label=actor_label,
    )

    with transaction.atomic():
        locked_scan = AnnualMembershipFeePostalScan.objects.select_for_update().get(pk=scan.pk)
        if (
            locked_scan.source_id != source_record.id
            or locked_scan.year != year
            or locked_scan.status not in allowed_statuses
            or locked_scan.payment_id
        ):
            return PostalScanReasoningRunResult(
                False,
                "AI推理中にPDFの状態が変わったため、結果を保存しませんでした。",
            )
        current_population = _build_postal_scan_candidate_population(
            source_record=source_record,
            year=year,
        )
        current_payload = _postal_scan_payload_for_reasoning(
            scan=locked_scan,
            batch=batch,
            source_record=source_record,
            candidate_population=current_population,
        )
        current_evidence, _current_local_candidates = _build_postal_scan_reasoning_evidence(
            scan=locked_scan,
            payload=current_payload,
            candidate_population=current_population,
        )
        if _postal_scan_reasoning_input_digest(current_evidence) != reasoning["input_digest"]:
            return PostalScanReasoningRunResult(
                False,
                "AI推理中に入金状況または候補が変わったため、結果を保存しませんでした。",
            )
        existing_runs = list((locked_scan.candidate_payload or {}).get("ai_reasoning_runs") or [])
        current_payload["ai_reasoning"] = reasoning
        current_payload["ai_reasoning_runs"] = [*existing_runs, reasoning][-10:]
        locked_scan.candidate_payload = current_payload
        locked_scan.save(update_fields=["candidate_payload", "updated_at"])

    if reasoning["recommendation_valid"]:
        return PostalScanReasoningRunResult(
            True,
            (
                f"AIは {reasoning['recommended_household_name']} を最も可能性の高い候補として"
                "推理しました。入金はまだ確定していません。"
            ),
        )
    return PostalScanReasoningRunResult(
        True,
        "AIの比較結果を保存しました。今回は候補を一つには絞っていません。",
    )


def _refresh_postal_scan_ai_reasoning_state(
    *,
    scan: AnnualMembershipFeePostalScan,
    payload: dict,
    candidate_population: _PostalScanCandidatePopulation | None,
) -> dict:
    reasoning = payload.get("ai_reasoning") or {}
    if not isinstance(reasoning, dict) or not reasoning:
        return payload
    refreshed_payload = dict(payload)
    refreshed_reasoning = _postal_scan_reasoning_for_display(reasoning)
    if candidate_population is None:
        refreshed_reasoning["stale"] = True
        refreshed_reasoning["recommendation_valid"] = False
        refreshed_reasoning["stale_message"] = (
            "現在の入金状況を再確認できないため、再推理してください。"
        )
        refreshed_payload["ai_reasoning"] = refreshed_reasoning
        return refreshed_payload
    evidence, local_candidates = _build_postal_scan_reasoning_evidence(
        scan=scan,
        payload=payload,
        candidate_population=candidate_population,
    )
    current_digest = _postal_scan_reasoning_input_digest(evidence)
    saved_identity_digest = _saved_postal_scan_reasoning_candidate_identity_digest(reasoning)
    current_identity_digest = _postal_scan_reasoning_candidate_identity_digest(local_candidates)
    if (
        current_digest != str(reasoning.get("input_digest") or "")
        or not saved_identity_digest
        or current_identity_digest != saved_identity_digest
    ):
        refreshed_reasoning["stale"] = True
        refreshed_reasoning["recommendation_valid"] = False
        refreshed_reasoning["stale_message"] = (
            "入金状況または候補が推理時から変わったため、AIの推薦を無効にしました。再推理してください。"
        )
    else:
        refreshed_reasoning["stale"] = False
        refreshed_reasoning["stale_message"] = ""
    refreshed_reasoning = _postal_scan_reasoning_for_display(
        refreshed_reasoning,
        local_candidates,
    )
    refreshed_payload["ai_reasoning"] = refreshed_reasoning
    return refreshed_payload


def build_postal_scan_review_context(
    *,
    source_id: str,
    source_record: LegacySource,
    batch: ImportBatch,
    year: int,
) -> dict:
    canonical_households = _active_canonical_households(source_id=source_record.source_id)
    ensure_postal_scan_year_directories(year)
    scan_objects = sorted(
        AnnualMembershipFeePostalScan.objects.select_related("payment").filter(
            source=source_record,
            year=year,
        ),
        key=_postal_scan_worklist_sort_key,
    )
    requires_candidate_rebuild = any(
        scan.status != AnnualMembershipFeePostalScan.Status.CHECKED
        and (
            (
                not list((scan.candidate_payload or {}).get("candidates") or [])
                and (
                    bool((scan.candidate_payload or {}).get("ocr"))
                    or bool(_postal_scan_receipt_details(scan).get("handling_office_name"))
                )
            )
            or any(
                candidate.get("candidate_source") == "handling_office"
                for candidate in list((scan.candidate_payload or {}).get("candidates") or [])
            )
            or bool((scan.candidate_payload or {}).get("ai_reasoning"))
        )
        for scan in scan_objects
    )
    candidate_population = (
        _build_postal_scan_candidate_population(source_record=source_record, year=year)
        if requires_candidate_rebuild
        else None
    )
    display_payloads = {
        scan.id: _postal_scan_candidate_payload_for_display(
            scan=scan,
            batch=batch,
            source_record=source_record,
            candidate_population=candidate_population,
        )
        for scan in scan_objects
    }
    candidate_household_ids = {
        str(candidate.get("legacy_household_id") or "").strip()
        for scan in scan_objects
        for candidate in list((display_payloads.get(scan.id) or {}).get("candidates") or [])
    }
    candidate_household_ids.update(
        str(
            ((display_payloads.get(scan.id) or {}).get("ai_reasoning") or {}).get(
                "recommended_household_uid"
            )
            or ""
        ).strip()
        for scan in scan_objects
    )
    candidate_household_ids.discard("")
    candidate_households = {
        household.household_uid: household
        for household in canonical_households.select_related("head_person").filter(
            household_uid__in=candidate_household_ids,
        )
    }
    candidate_profiles = {
        profile.household_uid: profile
        for profile in source_record.household_profiles.select_related("district").filter(
            household_uid__in=candidate_household_ids,
        )
    }
    candidate_payments = {
        payment.household_uid: payment
        for payment in AnnualMembershipFeePayment.objects.filter(
            source=source_record,
            year=year,
            household_uid__in=candidate_household_ids,
        )
    }
    scans = [
        _decorate_scan_for_context(
            scan,
            payload=display_payloads.get(scan.id),
            candidate_households=candidate_households,
            candidate_profiles=candidate_profiles,
            candidate_payments=candidate_payments,
        )
        for scan in scan_objects
        if not _is_summary_page(scan)
    ]
    pending_count = sum(
        1 for scan in scans if scan["status"] == AnnualMembershipFeePostalScan.Status.PENDING
    )
    needs_review_count = sum(
        1 for scan in scans if scan["status"] == AnnualMembershipFeePostalScan.Status.NEEDS_REVIEW
    )
    checked_count = sum(
        1 for scan in scans if scan["status"] == AnnualMembershipFeePostalScan.Status.CHECKED
    )
    action_required_count = len(scans) - checked_count
    ocr_count = sum(1 for scan in scans if scan["has_ocr"])
    ocr_progress = read_postal_scan_ocr_progress(year=year)
    return {
        "selected_source_id": source_id,
        "year": year,
        "scans": scans,
        "pending_count": pending_count,
        "needs_review_count": needs_review_count,
        "checked_count": checked_count,
        "action_required_count": action_required_count,
        "ocr_count": ocr_count,
        "ocr_progress": ocr_progress,
        "scan_count": len(scans),
        "storage_root": postal_scan_storage_root(),
        "pending_path": postal_scan_storage_root() / str(year) / "pending",
    }


def next_postal_scan_requiring_action_id(
    *,
    source_record: LegacySource,
    year: int,
) -> int | None:
    """Return the first visible scan still requiring an operator action."""

    scans = sorted(
        AnnualMembershipFeePostalScan.objects.filter(
            source=source_record,
            year=year,
        ).exclude(status=AnnualMembershipFeePostalScan.Status.CHECKED),
        key=_postal_scan_worklist_sort_key,
    )
    return next((scan.id for scan in scans if not _is_summary_page(scan)), None)


def _append_postal_scan_revision(
    payload: dict,
    *,
    scan: AnnualMembershipFeePostalScan,
    payment: AnnualMembershipFeePayment | None,
    actor_label: str,
) -> dict:
    return payment_services.append_postal_scan_revision(
        payload,
        scan=scan,
        payment=payment,
        actor_label=actor_label,
    )


def confirm_postal_scan_payment(
    *,
    active_source_id: str,
    source_record: LegacySource,
    batch: ImportBatch,
    scan: AnnualMembershipFeePostalScan,
    selected_household_id: str,
    year: int,
    received_on: date | None,
    default_amount: Decimal | None,
    actor_label: str = "",
    allow_reedit: bool = False,
) -> PostalScanConfirmResult:
    saved = payment_services.save_postal_scan_payment(
        active_source_id=active_source_id,
        source_record=source_record,
        scan=scan,
        selected_household_id=selected_household_id,
        year=year,
        received_on=received_on,
        default_amount=default_amount,
        actor_label=actor_label,
        receipt_details_loader=_postal_scan_receipt_details,
        allow_reedit=allow_reedit,
    )
    if not saved.success:
        return PostalScanConfirmResult(success=False, message=saved.message)
    scan = saved.scan
    assert scan is not None
    was_checked = saved.was_checked
    household_name = saved.household_name
    receipt_warning = saved.receipt_warning

    if was_checked:
        suffix = (
            " 案内不要設定の家ですが、実際の入金として記録しました。" if receipt_warning else ""
        )
        return PostalScanConfirmResult(
            success=True,
            message=f"{household_name} の確定内容を更新しました。{suffix}".strip(),
        )

    if not _scan_pdf_group_ready_for_move(scan):
        return PostalScanConfirmResult(
            success=True,
            message=f"{household_name} の護持会費を保存しました。元PDFは全ページ確認後に移動します。",
        )

    move_error = _move_scan_pdf_group_to_checked(scan)
    if move_error:
        return PostalScanConfirmResult(
            success=True,
            message=f"{household_name} の護持会費を保存しました。PDFの移動は未完了です。",
            move_error=move_error,
        )
    return PostalScanConfirmResult(
        success=True,
        message=f"{household_name} の護持会費を保存しました。元PDFを処理済みフォルダへ移動しました。",
    )


def mark_postal_scan_unknown_payment(
    *,
    source_record: LegacySource,
    scan: AnnualMembershipFeePostalScan,
    year: int,
    note: str = "",
    actor_label: str = "",
    allow_reedit: bool = False,
) -> PostalScanConfirmResult:
    saved = payment_services.save_postal_scan_unknown_payment(
        source_record=source_record,
        scan=scan,
        year=year,
        note=note,
        actor_label=actor_label,
        allow_reedit=allow_reedit,
    )
    if not saved.success:
        return PostalScanConfirmResult(success=False, message=saved.message)
    scan = saved.scan
    assert scan is not None
    was_checked = saved.was_checked

    if was_checked:
        return PostalScanConfirmResult(success=True, message="確定内容を不明入金へ変更しました。")

    if not _scan_pdf_group_ready_for_move(scan):
        return PostalScanConfirmResult(
            success=True,
            message="不明入金として記録しました。元PDFは全ページ確認後に移動します。",
        )

    move_error = _move_scan_pdf_group_to_checked(scan)
    if move_error:
        return PostalScanConfirmResult(
            success=True,
            message="不明入金として記録しました。PDFの移動は未完了です。",
            move_error=move_error,
        )
    return PostalScanConfirmResult(
        success=True,
        message="不明入金として記録しました。元PDFを処理済みフォルダへ移動しました。",
    )


def retry_postal_scan_pdf_move(scan: AnnualMembershipFeePostalScan) -> PostalScanConfirmResult:
    if not _scan_pdf_group_ready_for_move(scan, allow_move_error=True):
        return PostalScanConfirmResult(success=False, message="PDF移動の再実行対象ではありません。")
    move_error = _move_scan_pdf_group_to_checked(scan)
    if move_error:
        return PostalScanConfirmResult(
            success=False, message="PDFを移動できませんでした。", move_error=move_error
        )
    return PostalScanConfirmResult(success=True, message="PDFを処理済みフォルダへ移動しました。")


def verify_postal_scan_files(
    *,
    source_record: LegacySource | None = None,
    year: int | None = None,
) -> list[PostalScanVerificationIssue]:
    scans = AnnualMembershipFeePostalScan.objects.all()
    if source_record is not None:
        scans = scans.filter(source=source_record)
    if year is not None:
        scans = scans.filter(year=year)
    issues: list[PostalScanVerificationIssue] = []
    for scan in scans:
        _append_file_verification_issues(issues, scan=scan, kind="pdf")
        if scan.page_image_storage_key:
            _append_file_verification_issues(issues, scan=scan, kind="page")
        if scan.crop_storage_key:
            _append_file_verification_issues(issues, scan=scan, kind="crop")
        if (
            scan.status == AnnualMembershipFeePostalScan.Status.CHECKED
            and "/pending/" in scan.pdf_storage_key
            and _scan_pdf_group_ready_for_move(scan)
        ):
            issues.append(
                PostalScanVerificationIssue(
                    scan_id=scan.id,
                    storage_key=scan.pdf_storage_key,
                    kind="pdf",
                    message="処理済みですがPDFがpending側を指しています。",
                )
            )
    return issues


def _append_file_verification_issues(
    issues: list[PostalScanVerificationIssue],
    *,
    scan: AnnualMembershipFeePostalScan,
    kind: str,
) -> None:
    if kind == "crop":
        storage_key = scan.crop_storage_key
        expected_sha = scan.crop_sha256
    elif kind == "page":
        storage_key = scan.page_image_storage_key
        expected_sha = scan.page_image_sha256
    else:
        storage_key = scan.pdf_storage_key
        expected_sha = scan.pdf_sha256
    if not storage_key:
        return
    try:
        path = postal_scan_storage_path(storage_key)
    except ValueError as exc:
        issues.append(
            PostalScanVerificationIssue(
                scan_id=scan.id,
                storage_key=storage_key,
                kind=kind,
                message=str(exc),
            )
        )
        return
    if not path.exists():
        issues.append(
            PostalScanVerificationIssue(
                scan_id=scan.id,
                storage_key=storage_key,
                kind=kind,
                message="ファイルが見つかりません。",
            )
        )
        return
    actual_sha = calculate_file_sha256(path)
    if expected_sha and actual_sha != expected_sha:
        issues.append(
            PostalScanVerificationIssue(
                scan_id=scan.id,
                storage_key=storage_key,
                kind=kind,
                message="SHA256が一致しません。",
            )
        )


def _decorate_scan_for_context(
    scan: AnnualMembershipFeePostalScan,
    *,
    payload: dict | None = None,
    candidate_households: dict[str, Household] | None = None,
    candidate_profiles: dict[str, object] | None = None,
    candidate_payments: dict[str, AnnualMembershipFeePayment] | None = None,
) -> dict:
    payload = payload or scan.candidate_payload or {}
    receipt_details = payload.get("receipt_details") or _postal_scan_receipt_details(scan)
    payload = _candidate_payload_with_receipt_details(payload, receipt_details)
    candidates = [
        _hydrate_postal_scan_candidate_for_display(
            candidate,
            candidate_households=candidate_households or {},
            candidate_profiles=candidate_profiles or {},
            candidate_payments=candidate_payments or {},
            current_payment_id=scan.payment_id,
        )
        for candidate in matching_services.select_postal_scan_candidates(
            list(payload.get("candidates") or []),
        )
    ]
    ai_reasoning = dict(payload.get("ai_reasoning") or {})
    recommended_household_uid = str(ai_reasoning.get("recommended_household_uid") or "").strip()
    ai_recommended_candidate = None
    if (
        recommended_household_uid
        and ai_reasoning.get("recommendation_valid")
        and not ai_reasoning.get("stale")
    ):
        recommended_household = (candidate_households or {}).get(recommended_household_uid)
        if recommended_household is not None:
            recommended_profile = (candidate_profiles or {}).get(recommended_household_uid)
            ai_recommended_candidate = _postal_scan_candidate_record(
                household=recommended_household,
                profile=recommended_profile,
                head_name=_household_display_head_name(recommended_household),
                head_kana=_household_display_head_name_kana(recommended_household),
                score=0,
                match_reasons=[],
                candidate_source="ai_reasoning",
            )
    for candidate in candidates:
        candidate["ai_recommended"] = bool(
            ai_recommended_candidate
            and candidate.get("legacy_household_id") == recommended_household_uid
        )
    raw_ocr_payload = payload.get("ocr") or {}
    ocr_payload = _normalize_ocr_payload(raw_ocr_payload) if raw_ocr_payload else {}
    return {
        "id": scan.id,
        "status": scan.status,
        "status_label": scan.get_status_display(),
        "original_filename": scan.original_filename,
        "page_number": scan.page_number,
        "page_count": scan.page_count,
        "statement_date": scan.statement_date,
        "received_on_default": scan.statement_date or timezone.localdate(),
        "pdf_storage_key": scan.pdf_storage_key,
        "page_image_storage_key": scan.page_image_storage_key,
        "has_page_image": bool(scan.page_image_storage_key),
        "crop_storage_key": scan.crop_storage_key,
        "has_crop": bool(scan.crop_storage_key),
        "recognized_text": scan.recognized_text,
        "candidate_query": payload.get("query", ""),
        "candidate_notice": payload.get("candidate_notice", ""),
        "handling_office_evidence": payload.get("handling_office_evidence") or {},
        "ai_reasoning": ai_reasoning,
        "ai_recommended_candidate": ai_recommended_candidate,
        "ocr": ocr_payload,
        "has_ocr": bool(ocr_payload),
        "candidates": candidates,
        "top_candidate": candidates[0] if candidates else None,
        "receipt_details": receipt_details,
        "selected_legacy_household_id": scan.selected_household_uid,
        "selected_household_name_snapshot": scan.selected_household_name_snapshot,
        "confirmed_at": scan.confirmed_at,
        "confirmed_by": scan.confirmed_by,
        "move_error": scan.move_error,
        "payment_id": scan.payment_id,
        "can_reedit_existing_payment": bool(
            scan.status == AnnualMembershipFeePostalScan.Status.CHECKED and scan.payment_id
        ),
        "is_unknown_payment": bool((payload.get("unknown_payment") or {}).get("marked_at")),
        "unknown_payment_note": (payload.get("unknown_payment") or {}).get("note", ""),
    }


def _postal_scan_candidate_payload_for_display(
    *,
    scan: AnnualMembershipFeePostalScan,
    batch: ImportBatch,
    source_record: LegacySource,
    candidate_population: _PostalScanCandidatePopulation | None = None,
) -> dict:
    payload = scan.candidate_payload or {}
    receipt_details = _postal_scan_receipt_details(scan)
    payload = _candidate_payload_with_receipt_details(payload, receipt_details)
    payload = dict(payload)
    raw_ocr_payload = payload.get("ocr") or {}
    ocr_payload = _normalize_ocr_payload(raw_ocr_payload) if raw_ocr_payload else {}
    payload["ocr"] = ocr_payload
    has_saved_handling_candidate = any(
        candidate.get("candidate_source") == "handling_office"
        for candidate in list(payload.get("candidates") or [])
    )
    payload["candidates"] = matching_services.select_postal_scan_candidates(
        list(payload.get("candidates") or []),
    )
    has_handling_office_hint = bool(receipt_details.get("handling_office_name"))
    if (
        (payload.get("candidates") and not has_saved_handling_candidate)
        or (not ocr_payload and not has_handling_office_hint)
        or scan.status == AnnualMembershipFeePostalScan.Status.CHECKED
    ):
        return _refresh_postal_scan_ai_reasoning_state(
            scan=scan,
            payload=payload,
            candidate_population=candidate_population,
        )
    query = str(payload.get("query") or "")
    normalized_query = _normalize_search_text(query)
    allow_handling_office_hint = (
        not query.strip()
        or normalized_query
        == _normalize_search_text(str(receipt_details.get("handling_office_name") or ""))
        or query.strip() == (scan.recognized_text or "").strip()
    )
    refreshed_payload = build_postal_scan_candidate_payload(
        batch=batch,
        source_record=source_record,
        year=scan.year,
        query=query,
        ocr_payload=ocr_payload,
        receipt_details=receipt_details,
        allow_handling_office_hint=allow_handling_office_hint,
        candidate_population=candidate_population,
    )
    refreshed_payload = _candidate_payload_with_receipt_details(
        refreshed_payload, payload.get("receipt_details") or {}
    )
    if has_handling_office_hint:
        if payload.get("ai_reasoning"):
            refreshed_payload["ai_reasoning"] = payload["ai_reasoning"]
        return _refresh_postal_scan_ai_reasoning_state(
            scan=scan,
            payload=refreshed_payload,
            candidate_population=candidate_population,
        )
    selected_payload = refreshed_payload if refreshed_payload.get("candidates") else payload
    return _refresh_postal_scan_ai_reasoning_state(
        scan=scan,
        payload=selected_payload,
        candidate_population=candidate_population,
    )


def _hydrate_postal_scan_candidate_for_display(
    candidate: dict,
    *,
    candidate_households: dict[str, Household],
    candidate_profiles: dict[str, object],
    candidate_payments: dict[str, AnnualMembershipFeePayment],
    current_payment_id: int | None,
) -> dict:
    hydrated = dict(candidate)
    legacy_household_id = str(hydrated.get("legacy_household_id") or "").strip()
    household = candidate_households.get(legacy_household_id)
    if household is None:
        return hydrated
    profile = candidate_profiles.get(legacy_household_id)
    exclusion_reason = _annual_membership_fee_exclusion_reason(
        household=household,
        profile=profile,
    )
    can_receive_payment, receipt_warning = _postal_scan_receipt_policy(
        profile=profile,
        exclusion_reason=exclusion_reason,
    )
    payment = candidate_payments.get(legacy_household_id)
    already_paid = bool(payment is not None and payment.id != current_payment_id)
    payment_status_label = ""
    if already_paid and payment is not None:
        payment_details = []
        if payment.received_on:
            payment_details.append(payment.received_on.isoformat())
        if payment.amount is not None:
            payment_details.append(f"{payment.amount:g}円")
        payment_status_label = (
            f"当年度は入金済み（{' / '.join(payment_details)}）"
            if payment_details
            else "当年度は入金済み"
        )
    hydrated.update(
        _postal_scan_candidate_display_fields(
            household=household,
            profile=profile,
            head_name=_household_display_head_name(household),
            head_kana=_household_display_head_name_kana(household),
        )
    )
    hydrated.update(
        {
            "is_billable": not bool(exclusion_reason),
            "billing_note": exclusion_reason,
            "can_receive_payment": can_receive_payment and not already_paid,
            "receipt_warning": receipt_warning,
            "already_paid": already_paid,
            "payment_status_label": payment_status_label,
        }
    )
    return hydrated


def _postal_scan_candidate_display_fields(
    *,
    household: Household,
    profile,
    head_name: str,
    head_kana: str,
) -> dict:
    return {
        "household_name": head_name or household.household_uid,
        "head_name_kana": head_kana,
        "district_name": profile.district.name
        if profile is not None and profile.district_id
        else "",
        "delivery_method_label": HOUSEHOLD_DELIVERY_LABELS.get(
            profile.delivery_method if profile is not None else "",
            "",
        ),
        "postal_code": household.postal_code,
        "address_line1": household.address_line1,
        "address_line2": household.address_line2,
        "address_line3": household.address_line3,
        "address": _join_nonempty([household.address_line1, household.address_line2]),
        "phone": household.phone,
        "mobile": household.mobile,
        "mailing_name": profile.mailing_name if profile is not None else "",
        "mailing_address": _join_nonempty(
            [
                profile.mailing_postal_code if profile is not None else "",
                profile.mailing_address_line1 if profile is not None else "",
                profile.mailing_address_line2 if profile is not None else "",
            ]
        ),
        "mailing_phone": profile.mailing_phone if profile is not None else "",
    }


def _scan_pdf_group(scan: AnnualMembershipFeePostalScan):
    return pdf_move_services.scan_pdf_group(scan)


def _scan_pdf_slip_group(scan: AnnualMembershipFeePostalScan):
    return pdf_move_services.scan_pdf_slip_group(scan)


def _scan_pdf_group_ready_for_move(
    scan: AnnualMembershipFeePostalScan,
    *,
    allow_move_error: bool = False,
) -> bool:
    return pdf_move_services.scan_pdf_group_ready_for_move(
        scan,
        allow_move_error=allow_move_error,
    )


def _scan_has_payment_or_unknown_marker(scan: AnnualMembershipFeePostalScan):
    return pdf_move_services.scan_has_payment_or_unknown_marker(scan)


def _move_scan_pdf_group_to_checked(scan: AnnualMembershipFeePostalScan) -> str:
    return pdf_move_services.move_scan_pdf_group_to_checked(
        scan,
        storage_root=postal_scan_storage_root(),
    )


def _pdf_page_count(pdf_path: Path) -> int:
    return artifact_services.pdf_page_count(pdf_path)


def _extract_pdf_statement_date(pdf_path: Path) -> date | None:
    return statement_date_services.extract_pdf_statement_date(pdf_path)


def _parse_statement_date_text(text: str) -> date | None:
    return statement_date_services.parse_statement_date_text(text)


def _parse_receipt_details_text(text: str) -> dict:
    return receipt_services.parse_receipt_details_text(text)


def _extract_pdf_page_receipt_details(pdf_path: Path, page_number: int) -> dict:
    return receipt_services.extract_pdf_page_receipt_details(pdf_path, page_number)


def _candidate_payload_with_receipt_details(payload: dict, receipt_details: dict | None) -> dict:
    return receipt_services.with_receipt_details(payload, receipt_details)


def _postal_scan_receipt_details(scan: AnnualMembershipFeePostalScan) -> dict:
    cached_details = getattr(scan, "_postal_scan_receipt_details_cache", None)
    if isinstance(cached_details, dict):
        return cached_details
    stored_details = (scan.candidate_payload or {}).get("receipt_details") or {}
    stored_candidates = list((scan.candidate_payload or {}).get("candidates") or [])
    if stored_details.get("handling_office_name") or (
        stored_details
        and (stored_candidates or scan.status == AnnualMembershipFeePostalScan.Status.CHECKED)
    ):
        details = stored_details
    else:
        try:
            extracted_details = _extract_pdf_page_receipt_details(
                postal_scan_file_path(scan, kind="pdf"),
                scan.page_number,
            )
        except Exception:
            extracted_details = {}
        details = {**extracted_details, **stored_details}
    scan._postal_scan_receipt_details_cache = details
    return details


def postal_scan_receipt_details_for_display(scan: AnnualMembershipFeePostalScan) -> dict:
    return _postal_scan_receipt_details(scan)


def _postal_scan_net_amount(
    scan: AnnualMembershipFeePostalScan,
    *,
    receipt_details: dict | None = None,
) -> Decimal | None:
    receipt_details = receipt_details or _postal_scan_receipt_details(scan)
    return receipt_services.net_amount_from_receipt_details(receipt_details)


def _safe_date(year: int, month: int, day: int) -> date | None:
    return statement_date_services.safe_date(year, month, day)


# Compatibility names remain available; state ownership belongs to job_services.
_postal_scan_ocr_progress_path = job_services.progress_path
_postal_scan_ocr_stop_path = job_services.stop_path
_postal_scan_ocr_stop_requested = job_services.stop_requested
_clear_postal_scan_ocr_stop = job_services.clear_stop
_postal_scan_ocr_progress_snapshot = job_services.progress_snapshot
_write_postal_scan_ocr_progress = job_services.write_progress


def _join_nonempty(values: list[str | None]) -> str:
    return matching_services.join_nonempty(values)


def _update_existing_statement_dates(scans, statement_date: date | None) -> None:
    if statement_date is None:
        return
    for scan in scans:
        if scan.statement_date != statement_date:
            scan.statement_date = statement_date
            scan.save(update_fields=["statement_date", "updated_at"])


def _postal_slip_page_numbers(page_count: int) -> list[int]:
    return pdf_move_services.postal_slip_page_numbers(page_count)


def _postal_scan_worklist_sort_key(scan: AnnualMembershipFeePostalScan) -> tuple:
    return (
        _POSTAL_SCAN_WORKLIST_STATUS_ORDER.get(scan.status, 99),
        scan.original_filename.casefold(),
        scan.original_filename,
        scan.page_number,
        scan.id or 0,
    )


def _is_summary_page(scan: AnnualMembershipFeePostalScan) -> bool:
    return scan.page_count > 1 and scan.page_number == 1


def _create_page_artifacts_for_pdf(
    pdf_path: Path,
    *,
    year: int,
    pdf_sha256: str,
    page_count: int,
    page_numbers: list[int],
) -> list[dict]:
    return artifact_services.create_page_artifacts_for_pdf(
        pdf_path,
        year=year,
        pdf_sha256=pdf_sha256,
        page_count=page_count,
        page_numbers=page_numbers,
        storage_root=postal_scan_storage_root(),
        page_render_scale=PAGE_RENDER_SCALE,
        crop_box=DEFAULT_NAME_CROP_BOX,
    )


def _create_name_crop_for_page_image(
    page_image_path: Path,
    *,
    year: int,
    pdf_sha256: str,
    pdf_path: Path,
    page_number: int,
) -> dict:
    return artifact_services.create_name_crop_for_page_image(
        page_image_path,
        year=year,
        pdf_sha256=pdf_sha256,
        pdf_path=pdf_path,
        page_number=page_number,
        storage_root=postal_scan_storage_root(),
        crop_box=DEFAULT_NAME_CROP_BOX,
    )


def _default_recognition_text(pdf_path: Path) -> str:
    return artifact_services.default_recognition_text(pdf_path)


def _postal_scan_ocr_prompt() -> str:
    return ocr_services.postal_scan_ocr_prompt()


def _postal_scan_ocr_schema() -> dict[str, Any]:
    return ocr_services.postal_scan_ocr_schema()


def _scan_has_ai_ocr(scan: AnnualMembershipFeePostalScan) -> bool:
    ocr_payload = (scan.candidate_payload or {}).get("ocr") or {}
    return bool(
        ocr_payload.get("provider") == "openai"
        and (ocr_payload.get("name") or ocr_payload.get("address") or ocr_payload.get("phone"))
    )


def _postal_scan_ocr_target_scans(
    *,
    source_record: LegacySource,
    year: int,
    force: bool,
) -> tuple[list[AnnualMembershipFeePostalScan], int]:
    scans = list(
        AnnualMembershipFeePostalScan.objects.filter(
            source=source_record,
            year=year,
            payment__isnull=True,
        )
        .exclude(status=AnnualMembershipFeePostalScan.Status.CHECKED)
        .order_by("original_filename", "page_number", "id")
    )
    target_scans = []
    skipped_count = 0
    for scan in scans:
        if (
            _is_summary_page(scan)
            or not scan.crop_storage_key
            or (not force and _scan_has_ai_ocr(scan))
        ):
            skipped_count += 1
            continue
        target_scans.append(scan)
    return target_scans, skipped_count


def _start_postal_scan_ocr_background_thread(
    *,
    source_record_pk: int,
    batch_pk: int,
    year: int,
    force: bool,
    lease: job_services.RunLease,
) -> None:
    thread = threading.Thread(
        target=_run_postal_scan_ocr_batch_in_background,
        kwargs={
            "source_record_pk": source_record_pk, "batch_pk": batch_pk,
            "year": year, "force": force, "lease": lease,
        },
        daemon=True,
    )
    thread.start()


def _run_postal_scan_ocr_batch_in_background(
    *,
    source_record_pk: int,
    batch_pk: int,
    year: int,
    force: bool,
    lease: job_services.RunLease,
) -> None:
    try:
        close_old_connections()
        source_record = LegacySource.objects.get(pk=source_record_pk)
        batch = ImportBatch.objects.get(pk=batch_pk)
        _run_postal_scan_ocr_batch_locked(
            source_record=source_record, batch=batch, year=year, force=force, clear_stop=False,
        )
    except Exception as exc:
        job_services.record_failure(year=year, error=exc)
    finally:
        try:
            close_old_connections()
        finally:
            job_services.finish_run(year=year, lease=lease)


def _normalize_ocr_payload(payload: dict | None, *, model: str = "") -> dict[str, Any]:
    return ocr_services.normalize_ocr_payload(payload, model=model)


def _normalize_confidence_value(value: Any) -> float:
    return ocr_services.normalize_confidence_value(value)


def _recognized_text_from_ocr_payload(ocr_payload: dict) -> str:
    return ocr_services.recognized_text_from_ocr_payload(ocr_payload)


def _ocr_search_terms(ocr_payload: dict) -> list[str]:
    return matching_services.ocr_search_terms(ocr_payload)


def _candidate_score_for_scan(
    *,
    normalized_query: str,
    ocr_terms: list[str],
    ocr_phone_numbers: list[str],
    ocr_address: str,
    ocr_postal_code: str,
    normalized_ocr_address: str,
    household: Household,
    profile: HouseholdProfile | None,
    head_name: str,
    head_kana: str,
    household_member_names: list[tuple[str, str]] | None = None,
    query_terms: list[str] | None = None,
) -> tuple[int, list[str]]:
    return matching_services.candidate_score_for_scan(
        normalized_query=normalized_query,
        ocr_terms=ocr_terms,
        ocr_phone_numbers=ocr_phone_numbers,
        ocr_address=ocr_address,
        ocr_postal_code=ocr_postal_code,
        normalized_ocr_address=normalized_ocr_address,
        household=household,
        profile=profile,
        head_name=head_name,
        head_kana=head_kana,
        household_member_names=household_member_names,
        query_terms=query_terms,
    )


def _postal_scan_candidate_profile_is_relevant(profile) -> bool:
    return matching_services.postal_scan_candidate_profile_is_relevant(profile)


def _candidate_name_match(normalized_query: str, name: str, kana: str) -> tuple[int, str]:
    return matching_services.candidate_name_match(normalized_query, name, kana)


def _fuzzy_text_score(left: str, right: str) -> int:
    return matching_services.fuzzy_text_score(left, right)


def _dedupe_text_list(values: list[str]) -> list[str]:
    return matching_services.dedupe_text_list(values)


def _normalize_phone(value: str | None) -> str:
    return matching_services.normalize_phone(value)


def _normalize_phone_numbers(value: str | None) -> list[str]:
    return matching_services.normalize_phone_numbers(value)


def _candidate_phone_numbers(
    *, household: Household, profile: HouseholdProfile | None
) -> list[str]:
    return matching_services.candidate_phone_numbers(household=household, profile=profile)


def _phone_numbers_are_similar(left: str, right: str) -> bool:
    return matching_services.phone_numbers_are_similar(left, right)


def _phone_suffix_is_similar(left: str, right: str) -> bool:
    return matching_services.phone_suffix_is_similar(left, right)


def _bounded_levenshtein_distance(left: str, right: str, *, max_distance: int) -> int:
    return matching_services.bounded_levenshtein_distance(
        left,
        right,
        max_distance=max_distance,
    )


def _normalize_postal_code(value: str | None) -> str:
    return matching_services.normalize_postal_code(value)


def _address_match_for_ocr(
    *,
    ocr_address: str,
    normalized_ocr_address: str,
    household: Household,
    profile: HouseholdProfile | None,
) -> tuple[int, str]:
    return matching_services.address_match_for_ocr(
        ocr_address=ocr_address,
        normalized_ocr_address=normalized_ocr_address,
        household=household,
        profile=profile,
    )


def _address_score_for_text(
    *,
    ocr_address: str,
    normalized_ocr_address: str,
    stored_address: str,
) -> int:
    return matching_services.address_score_for_text(
        ocr_address=ocr_address,
        normalized_ocr_address=normalized_ocr_address,
        stored_address=stored_address,
    )


def _address_number_tokens(value: str | None) -> list[str]:
    return matching_services.address_number_tokens(value)


def _address_text_without_numbers(value: str) -> str:
    return matching_services.address_text_without_numbers(value)


def _longest_common_substring_length(left: str, right: str) -> int:
    return matching_services.longest_common_substring_length(left, right)


def _normalize_search_text(value: str | None) -> str:
    return matching_services.normalize_search_text(value)


def _storage_key_for_path(path: Path) -> str:
    return storage_services.storage_key_for_path(
        path,
        storage_root=postal_scan_storage_root(),
    )


def _checked_storage_key(scan: AnnualMembershipFeePostalScan) -> str:
    return storage_services.checked_storage_key(scan)


def _available_storage_key(storage_key: str) -> str:
    return storage_services.available_storage_key(
        storage_key,
        storage_root=postal_scan_storage_root(),
    )


def _available_storage_path(storage_key: str) -> Path:
    return storage_services.available_storage_path(
        storage_key,
        storage_root=postal_scan_storage_root(),
    )


def _write_uploaded_file(uploaded_file, destination_path: Path) -> None:
    storage_services.write_uploaded_file(uploaded_file, destination_path)


def _existing_postal_scan_pdf_label_by_sha256(
    *,
    source_record: LegacySource,
    year: int,
    pdf_sha256: str,
    exclude_path: Path,
) -> str:
    existing_scan = (
        AnnualMembershipFeePostalScan.objects.filter(
            source=source_record,
            year=year,
            pdf_sha256=pdf_sha256,
        )
        .order_by("original_filename", "page_number", "id")
        .first()
    )
    if existing_scan is not None:
        return existing_scan.original_filename
    exclude_path = exclude_path.resolve()
    for directory_name in ("pending", "checked"):
        directory = postal_scan_storage_root() / str(year) / directory_name
        for pdf_path in sorted(directory.glob("*.pdf")):
            if pdf_path.resolve() == exclude_path:
                continue
            try:
                if calculate_file_sha256(pdf_path) == pdf_sha256:
                    return f"{directory_name}/{pdf_path.name}"
            except OSError:
                continue
    return ""


def _pending_upload_destination_path(
    *,
    year: int,
    original_filename: str,
    pdf_sha256: str,
) -> Path:
    return storage_services.pending_upload_destination_path(
        year=year,
        original_filename=original_filename,
        pdf_sha256=pdf_sha256,
        storage_root=postal_scan_storage_root(),
    )


def _safe_filename(filename: str) -> str:
    return storage_services.safe_filename(filename)


def _safe_stem(path: Path) -> str:
    return storage_services.safe_stem(path)


__all__ = [
    "POSTAL_SCAN_PAYMENT_NOTE",
    "PostalScanContactSaveResult",
    "PostalScanConfirmResult",
    "PostalScanImportResult",
    "PostalScanOcrBatchResult",
    "PostalScanOcrClient",
    "PostalScanOcrError",
    "PostalScanOcrStartResult",
    "PostalScanPhoneSaveResult",
    "PostalScanReasoningClient",
    "PostalScanReasoningError",
    "PostalScanReasoningRunResult",
    "PostalScanUploadResult",
    "PostalScanVerificationIssue",
    "build_postal_scan_candidate_payload",
    "build_postal_scan_review_context",
    "calculate_file_sha256",
    "confirm_postal_scan_payment",
    "ensure_postal_scan_year_directories",
    "intake_postal_scan_pdfs",
    "mark_postal_scan_unknown_payment",
    "next_postal_scan_requiring_action_id",
    "postal_scan_file_path",
    "postal_scan_receipt_details_for_display",
    "postal_scan_storage_path",
    "postal_scan_storage_root",
    "read_postal_scan_ocr_progress",
    "request_postal_scan_ocr_stop",
    "retry_postal_scan_pdf_move",
    "run_postal_scan_ocr_batch",
    "run_postal_scan_ai_reasoning",
    "save_postal_scan_candidate_contact",
    "save_postal_scan_candidate_phone",
    "start_postal_scan_ocr_batch",
    "update_postal_scan_search_candidates",
    "upload_postal_scan_pdfs",
    "verify_postal_scan_files",
]
