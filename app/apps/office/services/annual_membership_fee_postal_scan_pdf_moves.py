from __future__ import annotations

import os
import shutil
from pathlib import Path

from django.db import connection, transaction
from django.utils import timezone

import apps.office.services.annual_membership_fee_postal_scan_storage as storage_services
from apps.imports.models import AnnualMembershipFeePostalScan

PDF_MOVE_PENDING_SOURCE_KEY = "_pdf_move_pending_source_key"


def postal_slip_page_numbers(page_count: int) -> list[int]:
    return [1] if page_count <= 1 else list(range(2, page_count + 1))


def scan_pdf_group(scan: AnnualMembershipFeePostalScan):
    return AnnualMembershipFeePostalScan.objects.filter(
        source_id=scan.source_id,
        year=scan.year,
        pdf_sha256=scan.pdf_sha256,
    )


def scan_pdf_slip_group(scan: AnnualMembershipFeePostalScan):
    return scan_pdf_group(scan).filter(
        page_number__in=postal_slip_page_numbers(scan.page_count or 1),
    )


def scan_has_payment_or_unknown_marker(scan: AnnualMembershipFeePostalScan) -> bool:
    if scan.payment_id:
        return True
    unknown_payment = (scan.candidate_payload or {}).get("unknown_payment") or {}
    return bool(unknown_payment.get("marked_at"))


def _group_ready(
    scans: list[AnnualMembershipFeePostalScan], *, page_count: int, allow_move_error: bool
) -> bool:
    if len(scans) < len(postal_slip_page_numbers(page_count or 1)):
        return False
    allowed_statuses = {AnnualMembershipFeePostalScan.Status.CHECKED}
    if allow_move_error:
        allowed_statuses.add(AnnualMembershipFeePostalScan.Status.MOVE_ERROR)
    return all(
        scan.status in allowed_statuses and scan_has_payment_or_unknown_marker(scan)
        for scan in scans
    )


def scan_pdf_group_ready_for_move(
    scan: AnnualMembershipFeePostalScan,
    *,
    allow_move_error: bool = False,
) -> bool:
    return _group_ready(
        list(scan_pdf_slip_group(scan)),
        page_count=scan.page_count,
        allow_move_error=allow_move_error,
    )


def _verified_pdf(path: Path, expected_hash: str) -> bool:
    return path.is_file() and storage_services.calculate_file_sha256(path) == expected_hash


def _existing_checked_copy(
    scan: AnnualMembershipFeePostalScan,
    *,
    storage_root: Path,
) -> Path | None:
    """Recover a verified copy, including files left by the former move-first code."""
    base_path = storage_services.postal_scan_storage_path(
        storage_services.checked_storage_key(scan),
        storage_root=storage_root,
    )
    if not base_path.parent.exists():
        return None
    for path in sorted(base_path.parent.iterdir()):
        suffix_number = path.stem.removeprefix(f"{base_path.stem}-")
        is_numbered_copy = (
            path.suffix == base_path.suffix
            and path.stem.startswith(f"{base_path.stem}-")
            and suffix_number.isdigit()
        )
        if (path.name == base_path.name or is_numbered_copy) and _verified_pdf(
            path,
            scan.pdf_sha256,
        ):
            return path
    return None


def _copy_pdf_without_overwrite(source: Path, destination: Path, *, expected_hash: str) -> None:
    created = False
    try:
        with source.open("rb") as input_file, destination.open("xb") as output_file:
            created = True
            shutil.copyfileobj(input_file, output_file)
            output_file.flush()
            os.fsync(output_file.fileno())
        if not _verified_pdf(destination, expected_hash):
            raise ValueError("コピー後のPDFのSHA256が登録内容と一致しません。")
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise


def _store_checked_group(
    scans: list[AnnualMembershipFeePostalScan],
    *,
    checked_key: str,
) -> None:
    for scan in scans:
        payload = dict(scan.candidate_payload or {})
        if scan.pdf_storage_key != checked_key:
            payload[PDF_MOVE_PENDING_SOURCE_KEY] = scan.pdf_storage_key
        scan.pdf_storage_key = checked_key
        scan.status = AnnualMembershipFeePostalScan.Status.CHECKED
        scan.move_error = ""
        scan.candidate_payload = payload
        scan.save(
            update_fields=[
                "pdf_storage_key",
                "status",
                "move_error",
                "candidate_payload",
                "updated_at",
            ]
        )


def _remove_pending_sources(
    scans: list[AnnualMembershipFeePostalScan],
    *,
    checked_path: Path,
    storage_root: Path,
) -> None:
    if not _verified_pdf(checked_path, scans[0].pdf_sha256):
        raise ValueError("処理済みPDFのSHA256を確認できないため、元PDFを保持しました。")
    source_keys = {
        str((scan.candidate_payload or {}).get(PDF_MOVE_PENDING_SOURCE_KEY) or "") for scan in scans
    } - {""}
    for source_key in source_keys:
        source_path = storage_services.postal_scan_storage_path(
            source_key,
            storage_root=storage_root,
        )
        if source_path == checked_path or not source_path.exists():
            continue
        if not _verified_pdf(source_path, scans[0].pdf_sha256):
            raise ValueError("元PDFのSHA256が登録内容と一致しないため、削除しません。")
        source_path.unlink()
    with transaction.atomic():
        for scan in scan_pdf_slip_group(scans[0]).select_for_update().order_by("pk"):
            payload = dict(scan.candidate_payload or {})
            if PDF_MOVE_PENDING_SOURCE_KEY in payload:
                payload.pop(PDF_MOVE_PENDING_SOURCE_KEY)
                scan.candidate_payload = payload
                scan.save(update_fields=["candidate_payload", "updated_at"])


def move_scan_pdf_group_to_checked(
    scan: AnnualMembershipFeePostalScan,
    *,
    storage_root: Path,
) -> str:
    """Copy, commit the new key, then remove the verified original; retry is safe.

    A surrounding atomic block cannot commit our storage key yet. Refuse storage
    work there, rather than deleting the original ahead of a possible rollback.
    """
    group = scan_pdf_slip_group(scan)
    created_path: Path | None = None
    mapping_saved = False
    try:
        if connection.in_atomic_block:
            raise RuntimeError("PDF移動は外側のtransaction確定後に再実行してください。")
        with transaction.atomic():
            scans = list(group.select_for_update().order_by("pk"))
            if not _group_ready(scans, page_count=scan.page_count, allow_move_error=True):
                raise ValueError("PDF移動には全明細ページの入金確認が必要です。")
            current_scan = next((row for row in scans if row.pk == scan.pk), scans[0])
            current_path = storage_services.postal_scan_storage_path(
                current_scan.pdf_storage_key,
                storage_root=storage_root,
            )
            if "/checked/" in current_scan.pdf_storage_key and _verified_pdf(
                current_path,
                current_scan.pdf_sha256,
            ):
                checked_path = current_path
            else:
                checked_path = _existing_checked_copy(current_scan, storage_root=storage_root)
                if checked_path is None:
                    if not _verified_pdf(current_path, current_scan.pdf_sha256):
                        raise FileNotFoundError(
                            f"登録内容と一致する元PDFが見つかりません: {current_path}"
                        )
                    checked_path = storage_services.available_storage_path(
                        storage_services.checked_storage_key(current_scan),
                        storage_root=storage_root,
                    )
                    checked_path.parent.mkdir(parents=True, exist_ok=True)
                    _copy_pdf_without_overwrite(
                        current_path,
                        checked_path,
                        expected_hash=current_scan.pdf_sha256,
                    )
                    created_path = checked_path
            checked_key = storage_services.storage_key_for_path(
                checked_path,
                storage_root=storage_root,
            )
            _store_checked_group(scans, checked_key=checked_key)
        mapping_saved = True
        _remove_pending_sources(scans, checked_path=checked_path, storage_root=storage_root)
        return ""
    except Exception as exc:
        # Until mapping_saved, pending still holds the original. Only our own
        # newly created, hash-verified copy may be compensated; never an older file.
        compensation_error = ""
        if created_path is not None and not mapping_saved:
            try:
                if _verified_pdf(created_path, scan.pdf_sha256):
                    created_path.unlink()
            except Exception as cleanup_exc:
                compensation_error = f" / コピー清掃未完了（再実行で回復できます）: {cleanup_exc}"
        error = f"{exc}{compensation_error}"
        group.update(
            status=AnnualMembershipFeePostalScan.Status.MOVE_ERROR,
            move_error=error,
            updated_at=timezone.now(),
        )
        return error


__all__ = [
    "PDF_MOVE_PENDING_SOURCE_KEY",
    "move_scan_pdf_group_to_checked",
    "postal_slip_page_numbers",
    "scan_has_payment_or_unknown_marker",
    "scan_pdf_group",
    "scan_pdf_group_ready_for_move",
    "scan_pdf_slip_group",
]
