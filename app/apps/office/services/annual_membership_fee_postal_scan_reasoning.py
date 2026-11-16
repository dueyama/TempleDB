from __future__ import annotations

import json
import os
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from apps.core.services import runtime_role

from .annual_membership_fee_postal_scan_ocr import (
    OPENAI_RESPONSES_URL,
    POSTAL_SCAN_OCR_MODEL,
)

POSTAL_SCAN_REASONING_MODEL = os.environ.get(
    "TEMPLEDB_POSTAL_SCAN_REASONING_MODEL",
    POSTAL_SCAN_OCR_MODEL,
)
POSTAL_SCAN_REASONING_EFFORT = os.environ.get(
    "TEMPLEDB_POSTAL_SCAN_REASONING_EFFORT",
    "medium",
)
POSTAL_SCAN_REASONING_TIMEOUT_SECONDS = float(
    os.environ.get("TEMPLEDB_POSTAL_SCAN_REASONING_TIMEOUT_SECONDS", "25")
)
POSTAL_SCAN_REASONING_MAX_CANDIDATES = 10
POSTAL_SCAN_REASONING_TOOL_NAME = "postal_scan_reasoning_result"
_CONTROL_CHARACTERS = {codepoint: None for codepoint in [*range(0x20), *range(0x7F, 0xA0)]}


class PostalScanReasoningError(RuntimeError):
    pass


class PostalScanReasoningClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        responses_url: str = OPENAI_RESPONSES_URL,
        timeout_seconds: float = POSTAL_SCAN_REASONING_TIMEOUT_SECONDS,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else os.environ.get("OPENAI_API_KEY") or ""
        ).strip()
        self.model = (model or POSTAL_SCAN_REASONING_MODEL).strip()
        self.reasoning_effort = (reasoning_effort or POSTAL_SCAN_REASONING_EFFORT).strip()
        self.responses_url = responses_url
        self.timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.model and runtime_role.openai_requests_allowed())

    @property
    def unavailable_reason(self) -> str:
        if not runtime_role.openai_requests_allowed():
            return runtime_role.openai_request_block_message()
        return "OPENAI_API_KEY が未設定です。"

    def reason(self, evidence: dict[str, Any]) -> dict[str, Any]:
        if not self.available:
            raise PostalScanReasoningError(self.unavailable_reason)
        candidates = list(evidence.get("candidates") or [])
        if not candidates:
            raise PostalScanReasoningError("AIが比較できる候補がありません。")
        if len(candidates) > POSTAL_SCAN_REASONING_MAX_CANDIDATES:
            raise PostalScanReasoningError(
                "候補が多すぎるため、検索条件を絞ってからAI推理を実行してください。"
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "store": False,
            "input": postal_scan_reasoning_prompt(evidence),
            "max_output_tokens": 1400,
            "parallel_tool_calls": False,
            "tool_choice": "required",
            "tools": [
                {
                    "type": "function",
                    "name": POSTAL_SCAN_REASONING_TOOL_NAME,
                    "description": "郵便振込の候補を事実だけから比較し、人が確認できる推理結果を返す",
                    "parameters": postal_scan_reasoning_schema(),
                    "strict": True,
                }
            ],
        }
        if self.model.startswith(("gpt-5.6", "gpt-6-luna", "gpt-6-sol")):
            payload["reasoning"] = {"effort": self.reasoning_effort}
        else:
            payload["temperature"] = 0.2
        response_json = self._post_json(payload)
        result = self._extract_function_arguments(response_json)
        normalized = normalize_reasoning_payload(result)
        normalized["model"] = self.model
        return normalized

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
                error_payload = json.loads(body)
            except Exception:  # pragma: no cover - defensive
                error_payload = {"error": {"message": str(exc)}}
            message = str(error_payload.get("error", {}).get("message") or str(exc))
            raise PostalScanReasoningError(message) from exc
        except urllib_error.URLError as exc:
            raise PostalScanReasoningError(str(exc.reason)) from exc
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise PostalScanReasoningError(str(exc)) from exc

    @staticmethod
    def _extract_function_arguments(response_json: dict[str, Any]) -> dict[str, Any]:
        for item in response_json.get("output", []):
            if item.get("type") != "function_call":
                continue
            if item.get("name") != POSTAL_SCAN_REASONING_TOOL_NAME:
                continue
            try:
                arguments = json.loads(item.get("arguments") or "{}")
            except (json.JSONDecodeError, TypeError) as exc:
                raise PostalScanReasoningError("AI推理結果を解析できませんでした。") from exc
            if not isinstance(arguments, dict):
                raise PostalScanReasoningError("AI推理結果の形式が正しくありません。")
            return arguments
        raise PostalScanReasoningError("AI推理結果が返りませんでした。")


def postal_scan_reasoning_prompt(evidence: dict[str, Any]) -> str:
    return "\n".join(
        [
            "寺院の郵便振込票について、誰からの入金かを候補同士で比較する。",
            "候補はc1、c2のような匿名キーであり、氏名や住所そのものは与えられていない。",
            "与えられた事実だけを使い、推測した事実を追加してはいけない。",
            "取扱店と住所地域の一致は参考情報であり、居住地や振込人の証明ではない。",
            "入金済み、またはcan_receive_payment=falseの候補は比較には使うが推薦してはいけない。",
            "請求対象外でもcan_receive_payment=trueなら、実入金として注意付き推薦はできる。",
            "根拠が足りない場合はrecommended_candidate_keyを空文字にする。",
            "reasoning_stepsは内部思考ではなく、人が検証できる短い根拠整理だけを書く。",
            "summary、interpretation、reason、uncertaintiesは利用者向けの自然な日本語で書く。",
            "これらの文章欄にはc1等の匿名キー、fact key、英語のfield名を出さない。",
            "全候補についてcandidate_assessmentsを返す。",
            "確定操作は人が行うため、needs_human_confirmationは必ずtrueにする。",
            "比較事実(JSON):",
            json.dumps(evidence, ensure_ascii=False, sort_keys=True),
        ]
    )


def postal_scan_reasoning_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "recommended_candidate_key": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "summary": {"type": "string"},
            "reasoning_steps": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "fact_keys": {
                            "type": "array",
                            "maxItems": 8,
                            "items": {"type": "string"},
                        },
                        "interpretation": {"type": "string"},
                    },
                    "required": ["fact_keys", "interpretation"],
                },
            },
            "candidate_assessments": {
                "type": "array",
                "maxItems": POSTAL_SCAN_REASONING_MAX_CANDIDATES,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "candidate_key": {"type": "string"},
                        "assessment": {
                            "type": "string",
                            "enum": ["most_likely", "possible", "unlikely", "ineligible"],
                        },
                        "reason": {"type": "string"},
                    },
                    "required": ["candidate_key", "assessment", "reason"],
                },
            },
            "uncertainties": {
                "type": "array",
                "maxItems": 6,
                "items": {"type": "string"},
            },
            "needs_human_confirmation": {"type": "boolean"},
        },
        "required": [
            "recommended_candidate_key",
            "confidence",
            "summary",
            "reasoning_steps",
            "candidate_assessments",
            "uncertainties",
            "needs_human_confirmation",
        ],
    }


def normalize_reasoning_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "recommended_candidate_key": _clean_text(payload.get("recommended_candidate_key")),
        "confidence": _normalize_confidence(payload.get("confidence")),
        "summary": _clean_text(payload.get("summary")),
        "reasoning_steps": [
            {
                "fact_keys": _dedupe_texts(item.get("fact_keys") or [])[:8],
                "interpretation": _clean_text(item.get("interpretation")),
            }
            for item in list(payload.get("reasoning_steps") or [])[:8]
            if isinstance(item, dict) and _clean_text(item.get("interpretation"))
        ],
        "candidate_assessments": [
            {
                "candidate_key": _clean_text(item.get("candidate_key")),
                "assessment": _clean_text(item.get("assessment")),
                "reason": _clean_text(item.get("reason")),
            }
            for item in list(payload.get("candidate_assessments") or [])[
                :POSTAL_SCAN_REASONING_MAX_CANDIDATES
            ]
            if isinstance(item, dict)
            and _clean_text(item.get("candidate_key"))
            and _clean_text(item.get("reason"))
        ],
        "uncertainties": _dedupe_texts(payload.get("uncertainties") or [])[:6],
        "needs_human_confirmation": True,
    }


def _clean_text(value: Any) -> str:
    return str(value or "").translate(_CONTROL_CHARACTERS).strip()


def _dedupe_texts(values: list[Any]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _normalize_confidence(value: Any) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "POSTAL_SCAN_REASONING_EFFORT",
    "POSTAL_SCAN_REASONING_MAX_CANDIDATES",
    "POSTAL_SCAN_REASONING_MODEL",
    "POSTAL_SCAN_REASONING_TIMEOUT_SECONDS",
    "PostalScanReasoningClient",
    "PostalScanReasoningError",
    "normalize_reasoning_payload",
    "postal_scan_reasoning_prompt",
    "postal_scan_reasoning_schema",
]
