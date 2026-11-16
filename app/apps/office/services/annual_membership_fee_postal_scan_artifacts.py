from __future__ import annotations

import re
from pathlib import Path

import apps.office.services.annual_membership_fee_postal_scan_storage as storage_services

PAGE_RENDER_SCALE = 2
DEFAULT_NAME_CROP_BOX = {
    "left": 0.06,
    "top": 0.50,
    "right": 0.60,
    "bottom": 0.82,
}


def pdf_page_count(pdf_path: Path) -> int:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - dependency check path
        raise RuntimeError("PDF全ページ展開には pypdfium2 が必要です。") from exc

    with pdfium.PdfDocument(str(pdf_path)) as document:
        page_count = len(document)
    if page_count <= 0:
        raise RuntimeError("PDFにページがありません。")
    return page_count


def create_page_artifacts_for_pdf(
    pdf_path: Path,
    *,
    year: int,
    pdf_sha256: str,
    page_count: int,
    page_numbers: list[int],
    storage_root: Path | None = None,
    page_render_scale: int = PAGE_RENDER_SCALE,
    crop_box: dict | None = None,
) -> list[dict]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - dependency check path
        raise RuntimeError("PDF全ページ展開には pypdfium2 が必要です。") from exc

    results: list[dict] = []
    requested_pages = set(page_numbers)
    with pdfium.PdfDocument(str(pdf_path)) as document:
        for page_index in range(len(document)):
            page_number = page_index + 1
            if page_number not in requested_pages:
                continue
            result = {
                "page_number": page_number,
                "page_count": page_count,
            }
            try:
                page = document[page_index]
                try:
                    bitmap = page.render(scale=page_render_scale)
                    try:
                        image = bitmap.to_pil()
                        try:
                            image.load()
                            page_key = storage_services.available_storage_key(
                                f"{year}/pages/{pdf_sha256[:12]}-"
                                f"{storage_services.safe_stem(pdf_path)}-p{page_number:03d}.png",
                                storage_root=storage_root,
                            )
                            page_path = storage_services.postal_scan_storage_path(
                                page_key,
                                storage_root=storage_root,
                            )
                            page_path.parent.mkdir(parents=True, exist_ok=True)
                            image.save(page_path, format="PNG")
                        finally:
                            image.close()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
                result["page_image_storage_key"] = page_key
                result["page_image_sha256"] = storage_services.calculate_file_sha256(page_path)
                result.update(
                    create_name_crop_for_page_image(
                        page_path,
                        year=year,
                        pdf_sha256=pdf_sha256,
                        pdf_path=pdf_path,
                        page_number=page_number,
                        storage_root=storage_root,
                        crop_box=crop_box,
                    )
                )
            except Exception as exc:
                result["error"] = str(exc)
            results.append(result)
    return results


def create_name_crop_for_page_image(
    page_image_path: Path,
    *,
    year: int,
    pdf_sha256: str,
    pdf_path: Path,
    page_number: int,
    storage_root: Path | None = None,
    crop_box: dict | None = None,
) -> dict:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - dependency check path
        raise RuntimeError("PDF切り抜きには Pillow が必要です。") from exc

    try:
        image = Image.open(page_image_path)
        image.load()
        image = ImageOps.exif_transpose(image).convert("RGB")
        effective_crop_box = dict(crop_box or DEFAULT_NAME_CROP_BOX)
        left = max(int(round(image.width * effective_crop_box["left"])), 0)
        top = max(int(round(image.height * effective_crop_box["top"])), 0)
        right = min(int(round(image.width * effective_crop_box["right"])), image.width)
        bottom = min(int(round(image.height * effective_crop_box["bottom"])), image.height)
        if right <= left or bottom <= top:
            raise ValueError("名前欄crop範囲が空です。")
        crop = image.crop((left, top, right, bottom))
        crop_key = storage_services.available_storage_key(
            f"{year}/crops/{pdf_sha256[:12]}-{storage_services.safe_stem(pdf_path)}-p{page_number:03d}.png",
            storage_root=storage_root,
        )
        crop_path = storage_services.postal_scan_storage_path(
            crop_key,
            storage_root=storage_root,
        )
        crop_path.parent.mkdir(parents=True, exist_ok=True)
        crop.save(crop_path, format="PNG")
        return {
            "crop_storage_key": crop_key,
            "crop_sha256": storage_services.calculate_file_sha256(crop_path),
            "crop_box": {
                **effective_crop_box,
                "pixel_left": left,
                "pixel_top": top,
                "pixel_right": right,
                "pixel_bottom": bottom,
            },
        }
    except Exception as exc:
        return {"error": str(exc)}


def default_recognition_text(pdf_path: Path) -> str:
    stem = pdf_path.stem
    stem = re.sub(r"^[0-9a-f]{8,16}[-_]", "", stem, flags=re.IGNORECASE)
    return stem.strip()


__all__ = [
    "DEFAULT_NAME_CROP_BOX",
    "PAGE_RENDER_SCALE",
    "create_name_crop_for_page_image",
    "create_page_artifacts_for_pdf",
    "default_recognition_text",
    "pdf_page_count",
]
