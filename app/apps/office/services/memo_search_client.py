from __future__ import annotations

import json
import os
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from django.utils import timezone

from apps.core.services import runtime_role

from .memo_search_shared import (
    DEFAULT_MEMO_AI_MODELS,
    MAX_AI_NEW_TAGS_PER_NOTE,
    MAX_AI_RERANK_CANDIDATES,
    MAX_AI_TAGS_PER_NOTE,
    OPENAI_QUERY_TIMEOUT_SECONDS,
    OPENAI_RERANK_TIMEOUT_SECONDS,
    OPENAI_RESPONSES_URL,
    OPENAI_TAG_TIMEOUT_SECONDS,
    QueryPlan,
    _dedupe_text_list,
    _excerpt,
)


class OpenAIResponsesError(RuntimeError):
    pass


class OpenAIResponsesClient:
    def __init__(self) -> None:
        self.api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        self.models = DEFAULT_MEMO_AI_MODELS

    @property
    def available(self) -> bool:
        return bool(
            self.api_key
            and self.models
            and runtime_role.openai_requests_allowed()
        )

    def suggest_tags(
        self,
        *,
        note_type_label: str,
        note_text: str,
        existing_labels: list[str],
        rule_labels: list[str],
    ) -> dict[str, Any]:
        prompt = "\n".join(
            [
                "寺院実務メモへ短い日本語タグを付ける。",
                "既存タグを優先して使う。",
                "新規タグは本当に必要な場合だけ最大2個まで。",
                "新規タグは再利用しやすい一般名詞にする。",
                "人名・日付・固有住所・長文は禁止。",
                f"メモ種別: {note_type_label}",
                f"既存タグ候補: {', '.join(existing_labels) if existing_labels else 'なし'}",
                f"規則ベース候補: {', '.join(rule_labels) if rule_labels else 'なし'}",
                "メモ本文:",
                note_text,
            ]
        )
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "selected_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": MAX_AI_TAGS_PER_NOTE,
                },
                "proposed_new_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": MAX_AI_NEW_TAGS_PER_NOTE,
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "needs_review": {"type": "boolean"},
            },
            "required": ["selected_labels", "proposed_new_labels", "confidence", "needs_review"],
        }
        return self._call_function(
            prompt=prompt,
            tool_name="memo_tag_response",
            tool_description="寺院メモへ再利用可能な日本語タグを返す",
            schema=schema,
            timeout_seconds=OPENAI_TAG_TIMEOUT_SECONDS,
        )

    def plan_query(
        self,
        *,
        query: str,
        tag_labels: list[str],
        note_types: list[dict[str, str]],
        result_kinds: list[dict[str, str]],
    ) -> QueryPlan:
        from .memo_search_query import _clean_search_keywords

        today_label = timezone.localdate().isoformat()
        prompt = "\n".join(
            [
                "寺院実務メモ検索の検索文を、意味検索向けの条件へ分解する。",
                "結果種別候補から最大4個まで選ぶ。",
                "既存タグ候補から最大5個まで選ぶ。",
                "メモ種別候補から最大4個まで選ぶ。",
                "補助キーワードを最大6個まで返す。",
                "相対日付がある場合は date_from/date_to を YYYY-MM-DD で返す。",
                "相対日付が無い場合は date_from/date_to を空文字にする。",
                f"今日の日付: {today_label}",
                "タグは新規作成しない。",
                "結果種別候補:",
                ", ".join(f"{item['key']}={item['label']}" for item in result_kinds),
                f"既存タグ候補: {', '.join(tag_labels) if tag_labels else 'なし'}",
                "メモ種別候補:",
                ", ".join(f"{item['key']}={item['label']}" for item in note_types),
                f"検索文: {query}",
            ]
        )
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "intent_summary": {"type": "string"},
                "result_kinds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 4,
                },
                "selected_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 5,
                },
                "selected_note_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 4,
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 6,
                },
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
            },
            "required": [
                "intent_summary",
                "result_kinds",
                "selected_labels",
                "selected_note_types",
                "keywords",
                "date_from",
                "date_to",
            ],
        }
        payload = self._call_function(
            prompt=prompt,
            tool_name="memo_query_plan",
            tool_description="検索文をタグ候補とメモ種別へ分解する",
            schema=schema,
            timeout_seconds=OPENAI_QUERY_TIMEOUT_SECONDS,
        )
        return QueryPlan(
            intent_summary=(payload.get("intent_summary") or "").strip(),
            result_kinds=_dedupe_text_list(payload.get("result_kinds") or []),
            selected_labels=_dedupe_text_list(payload.get("selected_labels") or []),
            selected_note_types=_dedupe_text_list(payload.get("selected_note_types") or []),
            keywords=_clean_search_keywords(payload.get("keywords") or []),
            date_from=str(payload.get("date_from") or "").strip(),
            date_to=str(payload.get("date_to") or "").strip(),
            used_ai=True,
            model=str(payload.get("_model") or ""),
        )

    def rerank_search_results(
        self,
        *,
        query: str,
        entries: list[dict[str, Any]],
    ) -> list[str]:
        if not entries:
            return []
        candidates = []
        for index, entry in enumerate(entries[:MAX_AI_RERANK_CANDIDATES], start=1):
            candidates.append(
                {
                    "key": f"c{index}",
                    "result_kind": entry.get("result_kind", ""),
                    "note_type": entry.get("note_type", ""),
                    "title": entry.get("title", ""),
                    "household_name": entry.get("household_name", ""),
                    "person_name": entry.get("person_name", ""),
                    "event_date": entry.get("event_date", ""),
                    "excerpt": _excerpt(entry.get("text", ""), length=160),
                }
            )
        prompt = "\n".join(
            [
                "寺院実務の検索候補を、問い合わせに近い順に並べ替える。",
                "無関係な候補は含めない。",
                "候補キーだけを返す。",
                f"問い合わせ: {query}",
                "候補一覧:",
                json.dumps(candidates, ensure_ascii=False),
            ]
        )
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "ordered_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": len(candidates),
                }
            },
            "required": ["ordered_keys"],
        }
        payload = self._call_function(
            prompt=prompt,
            tool_name="memo_search_rerank",
            tool_description="検索候補キーを関連度順に返す",
            schema=schema,
            timeout_seconds=OPENAI_RERANK_TIMEOUT_SECONDS,
        )
        return _dedupe_text_list(payload.get("ordered_keys") or [])

    def _call_function(
        self,
        *,
        prompt: str,
        tool_name: str,
        tool_description: str,
        schema: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if not runtime_role.openai_requests_allowed():
            raise OpenAIResponsesError(runtime_role.openai_request_block_message())
        if not self.available:
            raise OpenAIResponsesError("OPENAI_API_KEY is not configured.")
        last_error: Exception | None = None
        for model in self.models:
            payload = {
                "model": model,
                "store": False,
                "input": prompt,
                "max_output_tokens": 500,
                "tool_choice": "required",
                "tools": [
                    {
                        "type": "function",
                        "name": tool_name,
                        "description": tool_description,
                        "parameters": schema,
                        "strict": True,
                    }
                ],
            }
            if model.startswith(("gpt-5.6", "gpt-6-luna", "gpt-6-sol")):
                payload["reasoning"] = {"effort": "none"}
            else:
                payload["temperature"] = 0.2
            try:
                response_json = self._post_json(payload, timeout_seconds=timeout_seconds)
                parsed = self._extract_function_arguments(response_json, tool_name)
                parsed["_model"] = model
                return parsed
            except OpenAIResponsesError as exc:
                last_error = exc
                if "model" not in str(exc).lower():
                    break
            except Exception as exc:  # pragma: no cover - defensive
                last_error = exc
                break
        raise OpenAIResponsesError(str(last_error or "OpenAI request failed."))

    def _post_json(self, payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        request_body = json.dumps(payload).encode("utf-8")
        request = urllib_request.Request(
            OPENAI_RESPONSES_URL,
            data=request_body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8")
                payload = json.loads(body)
            except Exception:  # pragma: no cover - defensive
                payload = {"error": {"message": str(exc)}}
            message = str(payload.get("error", {}).get("message") or str(exc))
            raise OpenAIResponsesError(message) from exc
        except urllib_error.URLError as exc:
            raise OpenAIResponsesError(str(exc.reason)) from exc

    @staticmethod
    def _extract_function_arguments(response_json: dict[str, Any], tool_name: str) -> dict[str, Any]:
        for item in response_json.get("output", []):
            if item.get("type") != "function_call":
                continue
            if item.get("name") != tool_name:
                continue
            raw_arguments = item.get("arguments") or "{}"
            return json.loads(raw_arguments)
        raise OpenAIResponsesError("No function_call output was returned.")
