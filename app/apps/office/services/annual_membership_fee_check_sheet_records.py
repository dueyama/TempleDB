from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.imports.models import (
    AnnualMembershipFeeCheckSheetScan,
    ImportBatch,
    LegacySource,
)
from config import runtime_paths

from . import annual_membership_fee_mutations
from .annual_membership_fee_check_sheet_scan import (
    DEFAULT_CHECK_THRESHOLD,
    MAX_SCAN_FILE_SIZE_BYTES,
    scan_annual_membership_fee_check_sheet_bytes,
)

CHECK_SHEET_SCAN_ROOT_NAME = "annual_membership_fee_check_sheet_scans"


@dataclass(slots=True)
class SavedCheckSheetScan:
    record: AnnualMembershipFeeCheckSheetScan
    result: dict
    created: bool


@dataclass(slots=True)
class CheckSheetScanRecordError(Exception):
    message: str


def check_sheet_scan_storage_root() -> Path:
    return runtime_paths.private_auxiliary_root() / CHECK_SHEET_SCAN_ROOT_NAME


def check_sheet_scan_storage_path(
    storage_key: str,
    *,
    storage_root: Path | None = None,
) -> Path:
    root = (storage_root or check_sheet_scan_storage_root()).resolve()
    candidate = (root / storage_key).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("check sheet scan storage key escapes the private scan root")
    return candidate


def check_sheet_scan_file_path(
    scan: AnnualMembershipFeeCheckSheetScan,
    *,
    storage_root: Path | None = None,
) -> Path:
    if not scan.file_storage_key:
        raise FileNotFoundError("check sheet scan file is not available")
    path = check_sheet_scan_storage_path(scan.file_storage_key, storage_root=storage_root)
    if not path.is_file():
        raise FileNotFoundError(path)
    if _calculate_file_sha256(path) != scan.file_sha256:
        raise ValueError("check sheet scan file checksum does not match the saved record")
    return path


def safe_original_filename(filename: str) -> str:
    normalized = str(filename or "").replace("\\", "/")
    cleaned = Path(normalized).name.strip().replace(":", "_")
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "_", cleaned)
    if cleaned in {"", ".", ".."}:
        cleaned = "check-sheet-scan"
    return cleaned[:255]


def _content_type_for_data(data: bytes) -> str:
    if data.startswith(b"%PDF"):
        return "application/pdf"
    try:
        from PIL import Image

        with Image.open(BytesIO(data)) as image:
            return Image.MIME.get(image.format or "", "application/octet-stream")
    except Exception:
        return "application/octet-stream"


def _storage_key_for_path(path: Path, *, storage_root: Path | None = None) -> str:
    root = (storage_root or check_sheet_scan_storage_root()).resolve()
    return path.resolve().relative_to(root).as_posix()


def _new_original_path(
    *,
    year: int,
    original_filename: str,
    file_sha256: str,
    storage_root: Path | None = None,
) -> Path:
    root = storage_root or check_sheet_scan_storage_root()
    safe_name = safe_original_filename(original_filename)
    key = f"{year}/originals/{file_sha256[:12]}-{uuid4().hex}-{safe_name}"
    return check_sheet_scan_storage_path(key, storage_root=root)


def _calculate_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_original_bytes(destination: Path, data: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        root = destination.parent.parent.parent
        for directory in (root, destination.parent.parent, destination.parent):
            if directory.exists():
                os.chmod(directory, 0o700)
    temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        if os.name == "posix":
            directory_descriptor = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _result_payload(result: dict) -> dict:
    return {
        "schema_version": 1,
        "renderer": "pypdfium2",
        "total_count": int(result["total_count"]),
        "checked_count": int(result["checked_count"]),
        "unchecked_count": int(result["unchecked_count"]),
        "threshold": float(result["threshold"]),
        "image_width": int(result["image_width"]),
        "image_height": int(result["image_height"]),
        "alignment_source": str(result["alignment_source"]),
        "detected_marker_count": int(result["detected_marker_count"]),
        "rows": [
            {
                "household_uid": str(row["household_id"]),
                "score": round(float(row["score"]), 12),
                "is_checked": bool(row["is_checked"]),
            }
            for row in result["rows"]
        ],
    }


def save_check_sheet_scan(
    *,
    context: dict,
    source_record: LegacySource,
    year: int,
    uploaded_file,
    uploaded_by: str,
    storage_root: Path | None = None,
) -> SavedCheckSheetScan:
    uploaded_file.seek(0)
    data = uploaded_file.read(MAX_SCAN_FILE_SIZE_BYTES + 1)
    if not data:
        raise CheckSheetScanRecordError("アップロードされたファイルが空です。")

    result = scan_annual_membership_fee_check_sheet_bytes(context=context, data=data)
    file_sha256 = hashlib.sha256(data).hexdigest()
    original_filename = safe_original_filename(getattr(uploaded_file, "name", ""))

    existing = AnnualMembershipFeeCheckSheetScan.objects.filter(
        source=source_record,
        year=year,
        file_sha256=file_sha256,
    ).first()
    if existing is not None:
        existing_path = check_sheet_scan_storage_path(
            existing.file_storage_key,
            storage_root=storage_root,
        )
        if existing_path.exists():
            if _calculate_file_sha256(existing_path) != file_sha256:
                raise CheckSheetScanRecordError(
                    "保存済み原本の内容が記録と一致しないため、再利用できません。"
                )
        else:
            _write_original_bytes(existing_path, data)
        return SavedCheckSheetScan(record=existing, result=result, created=False)

    destination = _new_original_path(
        year=year,
        original_filename=original_filename,
        file_sha256=file_sha256,
        storage_root=storage_root,
    )
    _write_original_bytes(destination, data)

    payload = _result_payload(result)
    try:
        with transaction.atomic():
            record = AnnualMembershipFeeCheckSheetScan.objects.create(
                source=source_record,
                year=year,
                status=AnnualMembershipFeeCheckSheetScan.Status.REVIEW,
                file_storage_key=_storage_key_for_path(destination, storage_root=storage_root),
                original_filename=original_filename,
                file_sha256=file_sha256,
                file_size_bytes=len(data),
                content_type=_content_type_for_data(data),
                threshold=float(result.get("threshold") or DEFAULT_CHECK_THRESHOLD),
                image_width=int(result.get("image_width") or 0),
                image_height=int(result.get("image_height") or 0),
                alignment_source=str(result.get("alignment_source") or ""),
                detected_marker_count=int(result.get("detected_marker_count") or 0),
                result_payload=payload,
                uploaded_by=str(uploaded_by or "")[:100],
            )
    except IntegrityError:
        destination.unlink(missing_ok=True)
        existing = AnnualMembershipFeeCheckSheetScan.objects.filter(
            source=source_record,
            year=year,
            file_sha256=file_sha256,
        ).first()
        if existing is None:
            raise
        return SavedCheckSheetScan(record=existing, result=result, created=False)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return SavedCheckSheetScan(record=record, result=result, created=True)


def recent_check_sheet_scans(
    *,
    source_record: LegacySource,
    year: int,
    limit: int = 20,
) -> list[AnnualMembershipFeeCheckSheetScan]:
    return list(
        AnnualMembershipFeeCheckSheetScan.objects.filter(
            source=source_record,
            year=year,
        ).order_by("-created_at", "-id")[:limit]
    )


def confirm_check_sheet_scan(
    *,
    scan_id: int,
    active_source_id: str,
    source_record: LegacySource,
    batch: ImportBatch,
    year: int,
    household_ids: list[str],
    received_on,
    default_amount,
    confirmed_by: str,
):
    requested_ids = list(dict.fromkeys(str(value) for value in household_ids if value))
    if not requested_ids:
        raise CheckSheetScanRecordError("受領へ反映する戸主を1件以上選択してください。")
    with transaction.atomic():
        try:
            scan = AnnualMembershipFeeCheckSheetScan.objects.select_for_update().get(
                pk=scan_id,
                source=source_record,
                year=year,
            )
        except AnnualMembershipFeeCheckSheetScan.DoesNotExist as exc:
            raise CheckSheetScanRecordError(
                "保存済みのチェックシート読取記録が見つかりません。"
            ) from exc
        if scan.status == AnnualMembershipFeeCheckSheetScan.Status.CONFIRMED:
            raise CheckSheetScanRecordError("このチェックシートはすでに受領反映済みです。")

        allowed_ids = {
            str(row.get("household_uid") or "")
            for row in (scan.result_payload or {}).get("rows", [])
            if row.get("household_uid")
        }
        if not set(requested_ids).issubset(allowed_ids):
            raise CheckSheetScanRecordError(
                "読取記録にない戸主が含まれるため、受領へ反映しませんでした。"
            )

        result = annual_membership_fee_mutations.apply_annual_membership_fee_bulk_receive(
            active_source_id=active_source_id,
            source_record=source_record,
            batch=batch,
            year=year,
            household_ids=requested_ids,
            received_on=received_on,
            default_amount=default_amount,
            editor_label=confirmed_by,
        )
        if (
            result.error_messages
            or result.skipped_count
            or result.saved_count != len(requested_ids)
        ):
            detail = " / ".join(result.error_messages) or "選択した全件を反映できませんでした。"
            raise CheckSheetScanRecordError(f"受領への反映を取り消しました。{detail}")
        scan.status = AnnualMembershipFeeCheckSheetScan.Status.CONFIRMED
        scan.confirmed_payload = {
            "schema_version": 1,
            "selected_household_uids": requested_ids,
            "saved_count": int(result.saved_count),
            "skipped_count": int(result.skipped_count),
            "received_on": received_on.isoformat() if received_on is not None else "",
        }
        scan.confirmed_by = str(confirmed_by or "")[:100]
        scan.confirmed_at = timezone.now()
        scan.save(
            update_fields=[
                "status",
                "confirmed_payload",
                "confirmed_by",
                "confirmed_at",
                "updated_at",
            ]
        )
    return scan, result


__all__ = [
    "CHECK_SHEET_SCAN_ROOT_NAME",
    "CheckSheetScanRecordError",
    "SavedCheckSheetScan",
    "check_sheet_scan_file_path",
    "check_sheet_scan_storage_path",
    "check_sheet_scan_storage_root",
    "confirm_check_sheet_scan",
    "recent_check_sheet_scans",
    "safe_original_filename",
    "save_check_sheet_scan",
]
