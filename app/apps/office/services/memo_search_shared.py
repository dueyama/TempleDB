from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from apps.core.services import tenant_policy

if TYPE_CHECKING:
    from apps.imports.models import MemoTagAssignment


MAX_DYNAMIC_MEMO_TAGS = int(os.environ.get("TEMPLEDB_MAX_DYNAMIC_MEMO_TAGS", "24"))
_DEFAULT_MEMO_AI_MODELS_VALUE = "gpt-6-luna"
DEFAULT_MEMO_AI_MODELS = [
    model.strip()
    for model in os.environ.get(
        "TEMPLEDB_MEMO_AI_MODELS",
        _DEFAULT_MEMO_AI_MODELS_VALUE,
    ).split(",")
    if model.strip()
]
OPENAI_RESPONSES_URL = os.environ.get("OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses")
OPENAI_TIMEOUT_SECONDS = float(os.environ.get("TEMPLEDB_OPENAI_TIMEOUT_SECONDS", "12"))
OPENAI_QUERY_TIMEOUT_SECONDS = float(
    os.environ.get("TEMPLEDB_OPENAI_QUERY_TIMEOUT_SECONDS", str(OPENAI_TIMEOUT_SECONDS))
)
OPENAI_RERANK_TIMEOUT_SECONDS = float(
    os.environ.get("TEMPLEDB_OPENAI_RERANK_TIMEOUT_SECONDS", str(min(OPENAI_TIMEOUT_SECONDS, 8.0)))
)
OPENAI_TAG_TIMEOUT_SECONDS = float(
    os.environ.get("TEMPLEDB_OPENAI_TAG_TIMEOUT_SECONDS", str(min(OPENAI_TIMEOUT_SECONDS, 6.0)))
)
MAX_AI_TAGS_PER_NOTE = 5
MAX_AI_NEW_TAGS_PER_NOTE = 2
MAX_AI_RERANK_CANDIDATES = int(os.environ.get("TEMPLEDB_MAX_AI_RERANK_CANDIDATES", "12"))
MAX_RENDERED_SEARCH_RESULTS = int(os.environ.get("TEMPLEDB_MAX_RENDERED_SEARCH_RESULTS", "120"))
MAX_AUTO_TAG_NOTES_PER_RUN = int(os.environ.get("TEMPLEDB_MAX_AUTO_TAG_NOTES_PER_RUN", "80"))
MAX_AUTO_TAG_AI_CALLS_PER_RUN = int(os.environ.get("TEMPLEDB_MAX_AUTO_TAG_AI_CALLS_PER_RUN", "3"))
SEARCH_KEYWORD_STOPWORDS = {
    "について",
    "こと",
    "もの",
    "ため",
    "よう",
    "ような",
    "です",
    "ます",
    "したい",
    "した",
    "する",
    "して",
    "ある",
    "いる",
    "など",
    "から",
    "まで",
    "メモ",
    "ノート",
    "記録",
    "関係",
}
SEARCH_KEYWORD_SUFFIXES = [
    "に関するメモ",
    "に関するノート",
    "に関する",
    "についてのメモ",
    "についてのノート",
    "のメモ",
    "のノート",
    "の関係",
    "メモ",
    "ノート",
    "について",
    "のこと",
    "の件",
    "を知りたい",
    "を探したい",
    "を探す",
    "を見たい",
    "が見たい",
]

MEMO_TAG_SEEDS = [
    {"label": "要確認", "description": "確認待ちや未確定事項"},
    {"label": "要電話", "description": "電話連絡が必要"},
    {"label": "日程調整", "description": "日程や予定の調整"},
    {"label": "葬儀", "description": "葬儀や通夜の話題"},
    {"label": "年忌", "description": "年忌法要や祥月命日"},
    {"label": "初盆", "description": "初盆や新盆"},
    {"label": "来寺予定", "description": "来寺や来訪の予定"},
    {"label": "自宅訪問", "description": "自宅訪問や出向き"},
    {"label": "郵送", "description": "郵送物や発送"},
    {"label": "住所確認", "description": "住所や宛先の確認"},
    {"label": "戸主変更", "description": "戸主や名義の変更"},
    {"label": "納骨", "description": "納骨や墓地の話題"},
    {"label": "会費", "description": "護持会費や納入"},
    {"label": "供物", "description": "供物や供花の話題"},
]

RULE_TAG_PATTERNS = {
    "要確認": [r"要確認", r"確認", r"未定", r"不明", r"保留", r"検討"],
    "要電話": [r"電話", r"tel", r"連絡", r"折り返し"],
    "日程調整": [r"日程", r"予定", r"都合", r"調整", r"延期", r"変更"],
    "葬儀": [r"葬儀", r"通夜", r"告別式", r"火葬", r"喪主"],
    "年忌": [r"年忌", r"回忌", r"祥月", r"法要", r"彼岸", r"盆経"],
    "初盆": [r"初盆", r"新盆"],
    "来寺予定": [r"来寺", r"来訪", r"寺へ", r"参る", r"お参り"],
    "自宅訪問": [r"訪問", r"伺", r"自宅", r"出向"],
    "郵送": [r"郵送", r"発送", r"投函", r"封筒", r"送付", r"ラベル"],
    "住所確認": [r"住所", r"転居", r"引越", r"宛先", r"返送"],
    "戸主変更": [r"戸主", r"名義", r"承継", r"差し替", r"変更"],
    "納骨": [r"納骨", r"墓", r"墓地", r"墓所", r"合祀"],
    "会費": [r"護持会", r"会費", r"納入", r"未納", r"集金"],
    "供物": [r"供物", r"供花", r"花代", r"菓子"],
}

NOTE_TYPE_DEFINITIONS = {
    "household_note": {"label": "戸主メモ"},
    "person_note": {"label": "個人メモ"},
    "deceased_note": {"label": "故人メモ"},
    "service_schedule_note": {"label": "予定メモ"},
    "visit_note_body": {"label": "訪問メモ"},
    "visit_note_next_action": {"label": "次回対応"},
    "postal_review_note": {"label": "郵送照合メモ"},
    "hand_delivery_review_note": {"label": "手配り照合メモ"},
    "district_member_sheet_note": {"label": "地区メモ"},
}

SEARCH_MODE_CHOICES = [
    {"key": "smart", "label": "AI意味検索"},
    {"key": "text", "label": "文字検索"},
]

RESULT_KIND_DEFINITIONS = {
    "household": {"label": "戸主"},
    "person": {"label": "人"},
    "schedule": {"label": "法要予定"},
    "memo": {"label": "メモ"},
}

_SEARCH_ALIASES = tenant_policy.search_aliases()

RESULT_KIND_QUERY_ALIASES = {
    "household": ["戸主", "檀家", "世帯"],
    "person": list(_SEARCH_ALIASES["result_kind"]["person"]),
    "schedule": ["法要", "法事", "回忌", "年忌", "祥月", "初盆", "葬儀"],
    "memo": ["メモ", "ノート", "記録", "相談", "対応"],
}

NOTE_TYPE_QUERY_ALIASES = {
    "household_note": ["戸主メモ", "家メモ"],
    "person_note": ["個人メモ", "人物メモ", "家族メモ"],
    "deceased_note": list(_SEARCH_ALIASES["note_type"]["deceased_note"]),
    "service_schedule_note": ["予定メモ", "法要メモ", "法事メモ", "葬儀メモ"],
    "visit_note_body": ["訪問メモ", "訪問"],
    "visit_note_next_action": ["次回対応", "次回メモ", "宿題"],
    "postal_review_note": ["郵送照合メモ", "郵送メモ"],
    "hand_delivery_review_note": ["手配り照合メモ", "手配りメモ"],
    "district_member_sheet_note": ["地区メモ"],
}

TAG_QUERY_ALIASES = {
    "要確認": ["要確認", "確認", "未定", "不明", "保留"],
    "要電話": ["要電話", "電話", "連絡", "折返し"],
    "日程調整": ["日程調整", "日程", "予定変更", "都合", "延期"],
    "葬儀": ["葬儀", "通夜", "告別式", "火葬"],
    "年忌": ["年忌", "回忌", "法事", "法要", "祥月"],
    "初盆": ["初盆", "新盆"],
    "来寺予定": ["来寺", "来訪", "寺へ来る"],
    "自宅訪問": ["訪問", "自宅", "伺う"],
    "郵送": ["郵送", "発送", "送付", "投函"],
    "住所確認": ["住所", "転居", "引越", "宛先"],
    "戸主変更": ["戸主変更", "名義変更", "戸主", "名義", "承継"],
    "納骨": ["納骨", "墓", "墓地", "合祀"],
    "会費": ["会費", "護持会", "納入", "未納"],
    "供物": ["供物", "供花", "花代"],
}


@dataclass
class QueryPlan:
    intent_summary: str
    result_kinds: list[str]
    selected_labels: list[str]
    selected_note_types: list[str]
    keywords: list[str]
    date_from: str
    date_to: str
    used_ai: bool
    model: str


@dataclass
class MemoTagWorkItem:
    entry: dict[str, Any]
    checksum: str
    existing_assignments: list[MemoTagAssignment]
    rule_labels: list[str]


def _dedupe_text_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _search_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _excerpt(value: str, *, length: int = 180) -> str:
    text = (value or "").strip()
    if len(text) <= length:
        return text
    return text[: length - 1].rstrip() + "…"


def _note_checksum(value: str) -> str:
    return hashlib.sha256((value or "").strip().encode("utf-8")).hexdigest()


def _date_to_text(value: date | None) -> str:
    if value is None:
        return ""
    return value.isoformat()
