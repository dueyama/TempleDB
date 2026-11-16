from __future__ import annotations

import hashlib
from pathlib import Path

from apps.imports.models import AnnualMembershipFeePostalScan
from config import runtime_paths

POSTAL_SCAN_ROOT_NAME = "annual_membership_fee_postal_scans"


def postal_scan_storage_root() -> Path:
    return runtime_paths.private_auxiliary_root() / POSTAL_SCAN_ROOT_NAME


def ensure_postal_scan_year_directories(
    year: int,
    *,
    storage_root: Path | None = None,
) -> dict[str, Path]:
    year_root = (storage_root or postal_scan_storage_root()) / str(year)
    paths = {
        "pending": year_root / "pending",
        "checked": year_root / "checked",
        "pages": year_root / "pages",
        "crops": year_root / "crops",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def postal_scan_storage_path(
    storage_key: str,
    *,
    storage_root: Path | None = None,
) -> Path:
    root = (storage_root or postal_scan_storage_root()).resolve()
    candidate = (root / storage_key).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("postal scan storage key escapes the private scan root")
    return candidate


def postal_scan_file_path(
    scan: AnnualMembershipFeePostalScan,
    *,
    kind: str,
    storage_root: Path | None = None,
) -> Path:
    if kind == "crop":
        storage_key = scan.crop_storage_key
    elif kind == "page":
        storage_key = scan.page_image_storage_key
    else:
        storage_key = scan.pdf_storage_key
    if not storage_key:
        raise FileNotFoundError("postal scan file is not available")
    path = postal_scan_storage_path(storage_key, storage_root=storage_root)
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def calculate_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def storage_key_for_path(path: Path, *, storage_root: Path | None = None) -> str:
    return path.resolve().relative_to((storage_root or postal_scan_storage_root()).resolve()).as_posix()


def checked_storage_key(scan: AnnualMembershipFeePostalScan) -> str:
    return f"{scan.year}/checked/{scan.pdf_sha256[:12]}-{safe_filename(scan.original_filename)}"


def available_storage_key(
    storage_key: str,
    *,
    storage_root: Path | None = None,
) -> str:
    root = storage_root or postal_scan_storage_root()
    path = postal_scan_storage_path(storage_key, storage_root=root)
    if not path.exists():
        return storage_key
    parent = Path(storage_key).parent
    stem = Path(storage_key).stem
    suffix = Path(storage_key).suffix
    for index in range(2, 1000):
        candidate = (parent / f"{stem}-{index}{suffix}").as_posix()
        if not postal_scan_storage_path(candidate, storage_root=root).exists():
            return candidate
    raise RuntimeError("空いている保存先ファイル名を作れません。")


def available_storage_path(
    storage_key: str,
    *,
    storage_root: Path | None = None,
) -> Path:
    root = storage_root or postal_scan_storage_root()
    return postal_scan_storage_path(
        available_storage_key(storage_key, storage_root=root),
        storage_root=root,
    )


def write_uploaded_file(uploaded_file, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with destination_path.open("wb") as output:
        if hasattr(uploaded_file, "chunks"):
            for chunk in uploaded_file.chunks():
                output.write(chunk)
            return
        while True:
            chunk = uploaded_file.read(1024 * 1024)
            if not chunk:
                return
            output.write(chunk)


def pending_upload_destination_path(
    *,
    year: int,
    original_filename: str,
    pdf_sha256: str,
    storage_root: Path | None = None,
) -> Path:
    root = storage_root or postal_scan_storage_root()
    cleaned_filename = safe_filename(original_filename)
    base_key = f"{year}/pending/{cleaned_filename}"
    base_path = postal_scan_storage_path(base_key, storage_root=root)
    if not base_path.exists():
        return base_path
    stem = Path(cleaned_filename).stem
    suffix = Path(cleaned_filename).suffix or ".pdf"
    return available_storage_path(
        f"{year}/pending/{stem}-{pdf_sha256[:12]}{suffix}",
        storage_root=root,
    )


def safe_filename(filename: str) -> str:
    cleaned = Path(filename).name.strip() or "scan.pdf"
    cleaned = cleaned.replace("/", "_").replace("\\", "_").replace(":", "_")
    return cleaned


def safe_stem(path: Path) -> str:
    stem = path.stem.strip() or "scan"
    stem = stem.replace("/", "_").replace("\\", "_").replace(":", "_")
    return stem


__all__ = [
    "POSTAL_SCAN_ROOT_NAME",
    "available_storage_key",
    "available_storage_path",
    "calculate_file_sha256",
    "checked_storage_key",
    "ensure_postal_scan_year_directories",
    "pending_upload_destination_path",
    "postal_scan_file_path",
    "postal_scan_storage_path",
    "postal_scan_storage_root",
    "safe_filename",
    "safe_stem",
    "storage_key_for_path",
    "write_uploaded_file",
]
