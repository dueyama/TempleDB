from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from django.utils import timezone

from apps.core.services import runtime_role

OPENAI_RESPONSES_URL = os.environ.get("OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses")
POSTAL_SCAN_OCR_MODEL = os.environ.get("TEMPLEDB_POSTAL_SCAN_OCR_MODEL", "gpt-6-luna")
POSTAL_SCAN_OCR_FALLBACK_MODEL = os.environ.get(
    "TEMPLEDB_POSTAL_SCAN_OCR_FALLBACK_MODEL",
    "gpt-6-sol",
)
POSTAL_SCAN_OCR_FALLBACK_CONFIDENCE = float(
    os.environ.get("TEMPLEDB_POSTAL_SCAN_OCR_FALLBACK_CONFIDENCE", "0.70")
)
POSTAL_SCAN_OCR_TIMEOUT_SECONDS = float(os.environ.get("TEMPLEDB_POSTAL_SCAN_OCR_TIMEOUT_SECONDS", "45"))
POSTAL_SCAN_OCR_MAX_NAME_CANDIDATES = 2
_OCR_CONTROL_CHARACTERS = {
    codepoint: None
    for codepoint in [*range(0x20), *range(0x7F, 0xA0)]
}


class PostalScanOcrError(RuntimeError):
    pass


class PostalScanOcrClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        fallback_model: str | None = None,
        fallback_confidence: float = POSTAL_SCAN_OCR_FALLBACK_CONFIDENCE,
        responses_url: str = OPENAI_RESPONSES_URL,
        timeout_seconds: float = POSTAL_SCAN_OCR_TIMEOUT_SECONDS,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.environ.get("OPENAI_API_KEY") or "").strip()
        self.model = (model or POSTAL_SCAN_OCR_MODEL).strip()
        self.fallback_model = (
            POSTAL_SCAN_OCR_FALLBACK_MODEL
            if fallback_model is None
            else fallback_model
        ).strip()
        self.fallback_confidence = max(0.0, min(float(fallback_confidence), 1.0))
        self.responses_url = responses_url
        self.timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return bool(
            self.api_key
            and self.model
            and runtime_role.openai_requests_allowed()
        )

    @property
    def unavailable_reason(self) -> str:
        if not runtime_role.openai_requests_allowed():
            return runtime_role.openai_request_block_message()
        return "OPENAI_API_KEY が未設定です。"

    def recognize_crop(self, crop_path: Path) -> dict[str, Any]:
        if not self.available:
            raise PostalScanOcrError(self.unavailable_reason)
        image_b64 = base64.b64encode(crop_path.read_bytes()).decode("ascii")
        primary_result = self._recognize_image_with_model(
            image_b64=image_b64,
            model=self.model,
        )
        if not self._fallback_needed(primary_result):
            return primary_result
        try:
            fallback_result = self._recognize_image_with_model(
                image_b64=image_b64,
                model=self.fallback_model,
            )
        except PostalScanOcrError:
            # A usable Luna result is safer than dropping the whole scan when the
            # optional second read is temporarily unavailable.
            return primary_result
        return (
            fallback_result
            if recognized_text_from_ocr_payload(fallback_result)
            else primary_result
        )

    def _recognize_image_with_model(
        self,
        *,
        image_b64: str,
        model: str,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "store": False,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": postal_scan_ocr_prompt(),
                        },
                        {
                            "type": "input_image",
                            "image_url": f"data:image/png;base64,{image_b64}",
                            "detail": "high",
                        },
                    ],
                }
            ],
            "max_output_tokens": 700,
            "tool_choice": "required",
            "tools": [
                {
                    "type": "function",
                    "name": "postal_scan_ocr_result",
                    "description": "郵便振込用紙の手書き欄から氏名、住所、電話番号を抽出する",
                    "parameters": postal_scan_ocr_schema(),
                    "strict": True,
                }
            ],
        }
        if model.startswith(("gpt-5.6", "gpt-6-luna", "gpt-6-sol")):
            payload["reasoning"] = {"effort": "none"}
        response_json = self._post_json(payload)
        result = self._extract_function_arguments(response_json)
        return normalize_ocr_payload(result, model=model)

    def _fallback_needed(self, result: dict[str, Any]) -> bool:
        return bool(
            self.fallback_model
            and self.fallback_model != self.model
            and normalize_confidence_value(result.get("confidence")) < self.fallback_confidence
        )

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_body = json.dumps(payload).encode("utf-8")
        request = urllib_request.Request(
            self.responses_url,
            data=request_body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8")
                payload = json.loads(body)
            except Exception:  # pragma: no cover - defensive
                payload = {"error": {"message": str(exc)}}
            message = str(payload.get("error", {}).get("message") or str(exc))
            raise PostalScanOcrError(message) from exc
        except urllib_error.URLError as exc:
            raise PostalScanOcrError(str(exc.reason)) from exc
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise PostalScanOcrError(str(exc)) from exc

    @staticmethod
    def _extract_function_arguments(response_json: dict[str, Any]) -> dict[str, Any]:
        for item in response_json.get("output", []):
            if item.get("type") != "function_call":
                continue
            if item.get("name") != "postal_scan_ocr_result":
                continue
            raw_arguments = item.get("arguments") or "{}"
            try:
                result = json.loads(raw_arguments)
            except (json.JSONDecodeError, TypeError) as exc:
                raise PostalScanOcrError("AI OCR結果を解析できませんでした。") from exc
            if not isinstance(result, dict):
                raise PostalScanOcrError("AI OCR結果の形式が正しくありません。")
            return result
        raise PostalScanOcrError("AI OCR結果が返りませんでした。")


def postal_scan_ocr_prompt() -> str:
    return "\n".join(
        [
            "日本の郵便振込用紙から切り抜いた手書き欄を読む。",
            "氏名を最優先にし、住所と電話番号も読める範囲で抽出する。",
            "不確かな文字は断定せず、氏名候補を複数返す。",
            "name_candidatesにはnameを含め、可能性が高い順に全体で最大2件だけ返す。",
            "電話番号は自宅番号と携帯番号のどちらかである可能性がある。",
            "住所や電話番号を氏名として混ぜない。",
        ]
    )


def postal_scan_ocr_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "name_candidates": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": POSTAL_SCAN_OCR_MAX_NAME_CANDIDATES,
            },
            "address": {"type": "string"},
            "phone": {"type": "string"},
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
            "notes": {"type": "string"},
        },
        "required": ["name", "name_candidates", "address", "phone", "confidence", "notes"],
    }


def normalize_ocr_payload(payload: dict | None, *, model: str = "") -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    name = _clean_ocr_text(payload.get("name"))
    candidates = _dedupe_text_list(
        [
            name,
            *[
                _clean_ocr_text(candidate)
                for candidate in payload.get("name_candidates") or []
            ],
        ]
    )[:POSTAL_SCAN_OCR_MAX_NAME_CANDIDATES]
    confidence = normalize_confidence_value(payload.get("confidence"))
    normalized = {
        "provider": _clean_ocr_text(payload.get("provider") or ("openai" if model else "")),
        "model": _clean_ocr_text(model or payload.get("model") or ""),
        "name": name,
        "name_candidates": candidates,
        "address": _clean_ocr_text(payload.get("address")),
        "phone": _clean_ocr_text(payload.get("phone")),
        "confidence": confidence,
        "notes": _clean_ocr_text(payload.get("notes")),
        "processed_at": _clean_ocr_text(payload.get("processed_at")),
    }
    if model and not normalized["processed_at"]:
        normalized["processed_at"] = timezone.now().isoformat()
    return normalized


def normalize_confidence_value(value: Any) -> float:
    if isinstance(value, dict):
        numeric_values = [
            normalize_confidence_value(item)
            for item in value.values()
            if item is not None and item != ""
        ]
        return min(numeric_values) if numeric_values else 0.0
    if isinstance(value, str):
        label_scores = {"low": 0.3, "medium": 0.6, "high": 0.9}
        lowered = value.strip().lower()
        if lowered in label_scores:
            return label_scores[lowered]
        try:
            return max(0.0, min(float(lowered), 1.0))
        except ValueError:
            return 0.0
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0


def recognized_text_from_ocr_payload(ocr_payload: dict) -> str:
    parts = []
    for key in ["name", "address", "phone"]:
        value = str(ocr_payload.get(key) or "").strip()
        if value:
            parts.append(value)
    parts.extend(str(value or "").strip() for value in ocr_payload.get("name_candidates") or [])
    return " ".join(_dedupe_text_list(parts))


def _dedupe_text_list(values: list[str]) -> list[str]:
    seen = set()
    cleaned = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return cleaned


def _clean_ocr_text(value: Any) -> str:
    return str(value or "").translate(_OCR_CONTROL_CHARACTERS).strip()


__all__ = [
    "OPENAI_RESPONSES_URL",
    "POSTAL_SCAN_OCR_FALLBACK_CONFIDENCE",
    "POSTAL_SCAN_OCR_FALLBACK_MODEL",
    "POSTAL_SCAN_OCR_MAX_NAME_CANDIDATES",
    "POSTAL_SCAN_OCR_MODEL",
    "POSTAL_SCAN_OCR_TIMEOUT_SECONDS",
    "PostalScanOcrClient",
    "PostalScanOcrError",
    "normalize_confidence_value",
    "normalize_ocr_payload",
    "postal_scan_ocr_prompt",
    "postal_scan_ocr_schema",
    "recognized_text_from_ocr_payload",
]
