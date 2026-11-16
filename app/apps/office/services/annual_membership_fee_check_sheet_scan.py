from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO

from .annual_membership_fee_check_sheet_pdf import build_annual_membership_fee_check_sheet_layout

DEFAULT_CHECK_THRESHOLD = 0.06
MARKER_DETECTION_THRESHOLD = 95
MARKER_DETECTION_MAX_DIMENSION = 3000
PDF_RENDER_SCALE = 1
MAX_SCAN_FILE_SIZE_BYTES = 25 * 1024 * 1024
MAX_SCAN_IMAGE_DIMENSION = 10_000
MAX_SCAN_IMAGE_PIXELS = 40_000_000


@dataclass(slots=True)
class CheckSheetScanError(Exception):
    message: str


def _load_pillow_image_from_bytes(data: bytes):
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing
        raise CheckSheetScanError("画像読取には Pillow が必要です。") from exc

    if not data:
        raise CheckSheetScanError("アップロードされたファイルが空です。")
    if len(data) > MAX_SCAN_FILE_SIZE_BYTES:
        raise CheckSheetScanError(
            "ファイルが大きすぎます。25MB以下の画像またはPDFを指定してください。"
        )

    if data.startswith(b"%PDF"):
        image = _load_pdf_first_page_with_pdfium(data)
    else:
        try:
            image = Image.open(BytesIO(data))
            _validate_image_dimensions(image.width, image.height)
            image.load()
        except Exception as exc:
            raise CheckSheetScanError(
                "画像を開けませんでした。JPEG/PNGまたはPDFを指定してください。"
            ) from exc
    image = ImageOps.exif_transpose(image)
    if image.height > image.width:
        image = image.rotate(90, expand=True)
    _validate_image_dimensions(image.width, image.height)
    return image.convert("L")


def _validate_image_dimensions(width: float, height: float) -> None:
    if (
        not math.isfinite(width)
        or not math.isfinite(height)
        or width <= 0
        or height <= 0
        or width > MAX_SCAN_IMAGE_DIMENSION
        or height > MAX_SCAN_IMAGE_DIMENSION
        or width * height > MAX_SCAN_IMAGE_PIXELS
    ):
        raise CheckSheetScanError("画像の寸法が大きすぎるため読み取れません。")


def _load_pdf_first_page_with_pdfium(data: bytes):
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - dependency check path
        raise CheckSheetScanError("PDF読取には pypdfium2 が必要です。") from exc

    try:
        with pdfium.PdfDocument(data) as document:
            if len(document) <= 0:
                raise CheckSheetScanError("PDFにページがありません。")
            if len(document) != 1:
                raise CheckSheetScanError("受領チェックシートは1ページのPDFを指定してください。")
            page = document[0]
            try:
                page_width, page_height = page.get_size()
                _validate_image_dimensions(
                    page_width * PDF_RENDER_SCALE,
                    page_height * PDF_RENDER_SCALE,
                )
                bitmap = page.render(scale=PDF_RENDER_SCALE)
                try:
                    rendered_image = bitmap.to_pil()
                    try:
                        rendered_image.load()
                        return rendered_image.copy()
                    finally:
                        rendered_image.close()
                finally:
                    bitmap.close()
            finally:
                page.close()
    except CheckSheetScanError:
        raise
    except Exception as exc:
        raise CheckSheetScanError(
            "PDFを画像化できませんでした。スキャン結果をPNGまたはJPEGでアップロードしてください。"
        ) from exc


def render_check_sheet_scan_pdf_preview_png(data: bytes) -> bytes:
    if not data.startswith(b"%PDF"):
        raise CheckSheetScanError("保存原本はPDFではありません。")
    image = _load_pdf_first_page_with_pdfium(data)
    try:
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    finally:
        image.close()


def _corner_search_regions(width: int, height: int) -> dict[str, tuple[int, int, int, int]]:
    search_width = min(width, max(int(width * 0.22), 160))
    search_height = min(height, max(int(height * 0.22), 120))
    return {
        "top_left": (0, 0, search_width, search_height),
        "top_right": (width - search_width, 0, width, search_height),
        "bottom_left": (0, height - search_height, search_width, height),
        "bottom_right": (width - search_width, height - search_height, width, height),
    }


def _component_center_for_marker(
    image, region: tuple[int, int, int, int]
) -> tuple[float, float] | None:
    left, top, right, bottom = region
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return None

    crop = image.crop(region)
    pixels = crop.load()
    visited = bytearray(width * height)
    best_component: tuple[float, int, int, int, int, int] | None = None
    min_area = max(10, int(width * height * 0.00003))
    max_area = max(min_area + 1, int(width * height * 0.16))

    for y in range(height):
        row_offset = y * width
        for x in range(width):
            start_index = row_offset + x
            if visited[start_index] or pixels[x, y] >= MARKER_DETECTION_THRESHOLD:
                continue

            stack = [(x, y)]
            visited[start_index] = 1
            area = 0
            min_x = max_x = x
            min_y = max_y = y
            while stack:
                current_x, current_y = stack.pop()
                area += 1
                min_x = min(min_x, current_x)
                max_x = max(max_x, current_x)
                min_y = min(min_y, current_y)
                max_y = max(max_y, current_y)
                for next_x, next_y in (
                    (current_x - 1, current_y),
                    (current_x + 1, current_y),
                    (current_x, current_y - 1),
                    (current_x, current_y + 1),
                ):
                    if next_x < 0 or next_x >= width or next_y < 0 or next_y >= height:
                        continue
                    next_index = (next_y * width) + next_x
                    if visited[next_index] or pixels[next_x, next_y] >= MARKER_DETECTION_THRESHOLD:
                        continue
                    visited[next_index] = 1
                    stack.append((next_x, next_y))

            component_width = max_x - min_x + 1
            component_height = max_y - min_y + 1
            if area < min_area or area > max_area or component_width < 3 or component_height < 3:
                continue
            aspect_ratio = component_width / component_height
            fill_ratio = area / (component_width * component_height)
            if not 0.45 <= aspect_ratio <= 2.2 or fill_ratio < 0.28:
                continue
            score = area * fill_ratio / (1.0 + abs(aspect_ratio - 1.0))
            if best_component is None or score > best_component[0]:
                best_component = (score, min_x, min_y, max_x, max_y, area)

    if best_component is None:
        return None
    _, min_x, min_y, max_x, max_y, _ = best_component
    return left + ((min_x + max_x + 1) / 2), top + ((min_y + max_y + 1) / 2)


def _detect_registration_markers(image, layout: dict) -> dict[str, tuple[float, float]]:
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - image loading already checked this
        return {}

    detection_image = image
    x_scale = 1.0
    y_scale = 1.0
    max_dimension = max(image.width, image.height)
    if max_dimension > MARKER_DETECTION_MAX_DIMENSION:
        resize_ratio = MARKER_DETECTION_MAX_DIMENSION / max_dimension
        detection_width = max(int(round(image.width * resize_ratio)), 1)
        detection_height = max(int(round(image.height * resize_ratio)), 1)
        try:
            resample_filter = Image.Resampling.BILINEAR
        except AttributeError:  # pragma: no cover - old Pillow fallback
            resample_filter = Image.BILINEAR
        detection_image = image.resize((detection_width, detection_height), resample_filter)
        x_scale = image.width / detection_width
        y_scale = image.height / detection_height

    regions = _corner_search_regions(detection_image.width, detection_image.height)
    detected: dict[str, tuple[float, float]] = {}
    for marker in layout.get("registration_markers", []):
        key = marker.get("key")
        if key not in regions:
            continue
        center = _component_center_for_marker(detection_image, regions[key])
        if center is not None:
            detected[key] = (center[0] * x_scale, center[1] * y_scale)
    return detected


def _marker_page_center(marker: dict, *, page_height_mm: float) -> tuple[float, float]:
    size = marker["size"]
    return marker["x"] + (size / 2), page_height_mm - marker["bottom_y"] - (size / 2)


def _solve_affine_coefficients(
    points: list[tuple[float, float]],
    targets: list[float],
) -> tuple[float, float, float] | None:
    count = len(points)
    sx = sum(point[0] for point in points)
    sy = sum(point[1] for point in points)
    sxx = sum(point[0] * point[0] for point in points)
    sxy = sum(point[0] * point[1] for point in points)
    syy = sum(point[1] * point[1] for point in points)
    st = sum(targets)
    sxt = sum(point[0] * target for point, target in zip(points, targets, strict=True))
    syt = sum(point[1] * target for point, target in zip(points, targets, strict=True))
    matrix = [
        [sxx, sxy, sx, sxt],
        [sxy, syy, sy, syt],
        [sx, sy, float(count), st],
    ]

    for pivot_index in range(3):
        pivot_row = max(
            range(pivot_index, 3), key=lambda row_index: abs(matrix[row_index][pivot_index])
        )
        if abs(matrix[pivot_row][pivot_index]) < 1e-9:
            return None
        if pivot_row != pivot_index:
            matrix[pivot_index], matrix[pivot_row] = matrix[pivot_row], matrix[pivot_index]
        pivot = matrix[pivot_index][pivot_index]
        for column_index in range(pivot_index, 4):
            matrix[pivot_index][column_index] /= pivot
        for row_index in range(3):
            if row_index == pivot_index:
                continue
            factor = matrix[row_index][pivot_index]
            for column_index in range(pivot_index, 4):
                matrix[row_index][column_index] -= factor * matrix[pivot_index][column_index]

    return matrix[0][3], matrix[1][3], matrix[2][3]


def _fit_affine_transform(
    points: list[tuple[float, float]],
    targets: list[tuple[float, float]],
) -> tuple[float, float, float, float, float, float] | None:
    if len(points) < 3 or len(points) != len(targets):
        return None
    x_coefficients = _solve_affine_coefficients(points, [target[0] for target in targets])
    y_coefficients = _solve_affine_coefficients(points, [target[1] for target in targets])
    if x_coefficients is None or y_coefficients is None:
        return None
    return (
        x_coefficients[0],
        x_coefficients[1],
        x_coefficients[2],
        y_coefficients[0],
        y_coefficients[1],
        y_coefficients[2],
    )


def _transform_point(alignment: dict, page_x: float, page_y: float) -> tuple[float, float]:
    a, b, c, d, e, f = alignment["matrix"]
    return (a * page_x) + (b * page_y) + c, (d * page_x) + (e * page_y) + f


def _default_alignment(*, image_width: int, image_height: int, layout: dict) -> dict:
    scale_x = image_width / layout["page_width_mm"]
    scale_y = image_height / layout["page_height_mm"]
    return {
        "source": "full_page",
        "detected_marker_count": 0,
        "matrix": (scale_x, 0.0, 0.0, 0.0, scale_y, 0.0),
    }


def _alignment_from_registration_markers(*, image, layout: dict) -> dict:
    detected = _detect_registration_markers(image, layout)
    page_centers = {
        marker["key"]: _marker_page_center(marker, page_height_mm=layout["page_height_mm"])
        for marker in layout.get("registration_markers", [])
    }
    points = []
    targets = []
    for key, detected_center in detected.items():
        page_center = page_centers.get(key)
        if page_center is not None:
            points.append(page_center)
            targets.append(detected_center)

    matrix = _fit_affine_transform(points, targets)
    if matrix is None:
        return _default_alignment(image_width=image.width, image_height=image.height, layout=layout)

    trial_alignment = {"matrix": matrix}
    top_left = _transform_point(trial_alignment, 0.0, 0.0)
    top_right = _transform_point(trial_alignment, layout["page_width_mm"], 0.0)
    bottom_left = _transform_point(trial_alignment, 0.0, layout["page_height_mm"])
    determinant = (matrix[0] * matrix[4]) - (matrix[1] * matrix[3])
    top_width = abs(top_right[0] - top_left[0]) + abs(top_right[1] - top_left[1])
    left_height = abs(bottom_left[0] - top_left[0]) + abs(bottom_left[1] - top_left[1])
    if abs(determinant) < 0.1 or top_width < 100 or left_height < 100:
        return _default_alignment(image_width=image.width, image_height=image.height, layout=layout)

    return {
        "source": "markers",
        "detected_marker_count": len(detected),
        "matrix": matrix,
    }


def _box_crop_bounds(
    *,
    box: dict,
    image_width: int,
    image_height: int,
    page_height_mm: float,
    alignment: dict,
) -> tuple[int, int, int, int]:
    inset = box["size"] * 0.24
    x0 = box["x"] + inset
    x1 = box["x"] + box["size"] - inset
    y0 = page_height_mm - (box["bottom_y"] + box["size"]) + inset
    y1 = page_height_mm - box["bottom_y"] - inset
    transformed_points = [
        _transform_point(alignment, x0, y0),
        _transform_point(alignment, x1, y0),
        _transform_point(alignment, x1, y1),
        _transform_point(alignment, x0, y1),
    ]
    left = max(int(round(min(point[0] for point in transformed_points))) - 1, 0)
    top = max(int(round(min(point[1] for point in transformed_points))) - 1, 0)
    right = min(int(round(max(point[0] for point in transformed_points))) + 1, image_width)
    bottom = min(int(round(max(point[1] for point in transformed_points))) + 1, image_height)
    return left, top, right, bottom


def _dark_ratio(image, bounds: tuple[int, int, int, int]) -> float:
    left, top, right, bottom = bounds
    if right <= left or bottom <= top:
        return 0.0
    crop = image.crop(bounds)
    histogram = crop.histogram()
    pixel_count = sum(histogram)
    if not pixel_count:
        return 0.0
    paper_peak = max(range(170, 256), key=lambda value: histogram[value])
    ink_threshold = min(190, max(135, paper_peak - 55))
    pixels = crop.load()
    width, height = crop.size
    visited = bytearray(width * height)
    min_component_area = max(5, int(round(pixel_count * 0.035)))
    dark_pixels = 0

    for y in range(height):
        row_offset = y * width
        for x in range(width):
            start_index = row_offset + x
            if visited[start_index] or pixels[x, y] >= ink_threshold:
                continue
            stack = [(x, y)]
            visited[start_index] = 1
            area = 0
            while stack:
                current_x, current_y = stack.pop()
                area += 1
                for next_x, next_y in (
                    (current_x - 1, current_y),
                    (current_x + 1, current_y),
                    (current_x, current_y - 1),
                    (current_x, current_y + 1),
                ):
                    if next_x < 0 or next_x >= width or next_y < 0 or next_y >= height:
                        continue
                    next_index = (next_y * width) + next_x
                    if visited[next_index] or pixels[next_x, next_y] >= ink_threshold:
                        continue
                    visited[next_index] = 1
                    stack.append((next_x, next_y))
            if area >= min_component_area:
                dark_pixels += area

    return dark_pixels / pixel_count


def scan_annual_membership_fee_check_sheet(
    *, context: dict, uploaded_file, threshold: float | None = None
) -> dict:
    uploaded_file.seek(0)
    data = uploaded_file.read(MAX_SCAN_FILE_SIZE_BYTES + 1)
    return scan_annual_membership_fee_check_sheet_bytes(
        context=context,
        data=data,
        threshold=threshold,
    )


def scan_annual_membership_fee_check_sheet_bytes(
    *,
    context: dict,
    data: bytes,
    threshold: float | None = None,
) -> dict:
    image = _load_pillow_image_from_bytes(data)
    layout = build_annual_membership_fee_check_sheet_layout(context=context)
    alignment = _alignment_from_registration_markers(image=image, layout=layout)
    threshold_value = threshold or DEFAULT_CHECK_THRESHOLD
    rows = []
    for box in layout["boxes"]:
        score = _dark_ratio(
            image,
            _box_crop_bounds(
                box=box,
                image_width=image.width,
                image_height=image.height,
                page_height_mm=layout["page_height_mm"],
                alignment=alignment,
            ),
        )
        rows.append(
            {
                "household_id": box["household_id"],
                "head_name": box["head_name"],
                "district_name": box["district_name"],
                "score": score,
                "score_percent": round(score * 100, 1),
                "is_checked": score >= threshold_value,
            }
        )
    checked_rows = [row for row in rows if row["is_checked"]]
    unchecked_rows = [row for row in rows if not row["is_checked"]]
    return {
        "rows": rows,
        "checked_rows": checked_rows,
        "unchecked_rows": unchecked_rows,
        "checked_count": len(checked_rows),
        "unchecked_count": len(unchecked_rows),
        "total_count": len(rows),
        "threshold": threshold_value,
        "image_width": image.width,
        "image_height": image.height,
        "alignment_source": alignment["source"],
        "detected_marker_count": alignment["detected_marker_count"],
    }


__all__ = [
    "CheckSheetScanError",
    "MAX_SCAN_FILE_SIZE_BYTES",
    "MAX_SCAN_IMAGE_DIMENSION",
    "MAX_SCAN_IMAGE_PIXELS",
    "PDF_RENDER_SCALE",
    "render_check_sheet_scan_pdf_preview_png",
    "scan_annual_membership_fee_check_sheet",
    "scan_annual_membership_fee_check_sheet_bytes",
]
