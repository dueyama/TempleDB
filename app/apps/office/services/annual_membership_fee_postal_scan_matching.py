from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

POSTAL_SCAN_MAX_CANDIDATES = 2
POSTAL_SCAN_STRONG_CANDIDATE_SCORE = 90
POSTAL_SCAN_PLAUSIBLE_ALTERNATIVE_SCORE = 70


def join_nonempty(values: list[str | None]) -> str:
    return " ".join(str(value or "").strip() for value in values if str(value or "").strip())


def ocr_search_terms(ocr_payload: dict) -> list[str]:
    terms = []
    for value in [
        ocr_payload.get("name"),
        *(ocr_payload.get("name_candidates") or []),
    ]:
        normalized = normalize_search_text(str(value or ""))
        if normalized:
            terms.append(normalized)
    return dedupe_text_list(terms)


def query_search_terms(query: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", str(query or "")).strip()
    return dedupe_text_list(
        [
            normalize_search_text(term)
            for term in re.split(r"[\s,、/／]+", normalized)
            if normalize_search_text(term)
        ]
    )


def candidate_score_for_scan(
    *,
    normalized_query: str,
    ocr_terms: list[str],
    ocr_phone_numbers: list[str],
    ocr_address: str,
    ocr_postal_code: str,
    normalized_ocr_address: str,
    household: Any,
    profile: Any | None,
    head_name: str,
    head_kana: str,
    household_member_names: list[tuple[str, str]] | None = None,
    query_terms: list[str] | None = None,
) -> tuple[int, list[str]]:
    member_names = household_member_names or []
    name_evidence = [(head_name, head_kana, "氏名", "氏名類似")]
    name_evidence.extend(
        (
            member_name,
            member_kana,
            f"家族氏名（{member_name}）",
            f"家族氏名類似（{member_name}）",
        )
        for member_name, member_kana in member_names
        if str(member_name or "").strip()
    )
    mailing_name = str(getattr(profile, "mailing_name", "") or "").strip()
    if mailing_name:
        name_evidence.append(
            (
                mailing_name,
                "",
                f"送付先氏名（{mailing_name}）",
                f"送付先氏名類似（{mailing_name}）",
            )
        )
    name_matches = []
    for term in [normalized_query, *ocr_terms]:
        if not term:
            continue
        for name, kana, exact_reason, similar_reason in name_evidence:
            name_score, base_reason = candidate_name_match(term, name, kana)
            if not name_score:
                continue
            reason = similar_reason if base_reason == "氏名類似" else exact_reason
            name_matches.append((name_score, reason))
    best_name_match = max(name_matches, key=lambda item: item[0]) if name_matches else (0, "")
    name_score, name_reason = best_name_match
    match_reasons: list[str] = []
    if name_score:
        match_reasons.append(name_reason or "氏名")
    household_phone_numbers = candidate_phone_numbers(household=household, profile=profile)
    phone_match = bool(ocr_phone_numbers and set(ocr_phone_numbers) & set(household_phone_numbers))
    phone_similar = bool(
        not phone_match
        and ocr_phone_numbers
        and any(
            phone_numbers_are_similar(ocr_phone, household_phone)
            for ocr_phone in ocr_phone_numbers
            for household_phone in household_phone_numbers
        )
    )
    postal_match = bool(
        ocr_postal_code
        and ocr_postal_code == normalize_postal_code(household.postal_code)
    )
    address_score, address_reason = address_match_for_ocr(
        ocr_address=ocr_address,
        normalized_ocr_address=normalized_ocr_address,
        household=household,
        profile=profile,
    )

    score = name_score
    if phone_match:
        match_reasons.append("電話一致")
        if name_score:
            score = max(score, min(100, name_score + 12), 95)
        elif postal_match or address_score:
            score = 92
        else:
            score = 88
    elif phone_similar:
        match_reasons.append("電話類似")
        if name_score or postal_match or address_score:
            score = max(score, min(100, score + 8), 80 if address_score else 72)
    if postal_match:
        match_reasons.append("郵便番号")
        score = min(100, score + 4) if score else 45
    if address_score:
        match_reasons.append(address_reason)
        score = min(100, score + 8) if score else address_score
    manual_query_match = multi_term_query_matches_candidate(
        query_terms=query_terms or [],
        household=household,
        profile=profile,
        head_name=head_name,
        head_kana=head_kana,
        household_member_names=member_names,
    )
    if manual_query_match and score < POSTAL_SCAN_STRONG_CANDIDATE_SCORE:
        score = 95
        match_reasons.insert(0, "検索語一致")
    if (
        not manual_query_match
        and score == name_score
        and name_score < 70
        and not (phone_match or phone_similar or postal_match or address_score)
    ):
        return 0, []
    return int(score), match_reasons


def multi_term_query_matches_candidate(
    *,
    query_terms: list[str],
    household: Any,
    profile: Any | None,
    head_name: str,
    head_kana: str,
    household_member_names: list[tuple[str, str]],
) -> bool:
    terms = dedupe_text_list(query_terms)
    if len(terms) < 2:
        return False
    member_values = [value for pair in household_member_names for value in pair]
    name_values = [
        head_name,
        head_kana,
        *member_values,
        getattr(profile, "mailing_name", "") if profile is not None else "",
    ]
    name_search_text = normalize_search_text(join_nonempty(name_values))
    district = getattr(profile, "district", None) if profile is not None else None
    all_search_text = normalize_search_text(
        join_nonempty(
            [
                *name_values,
                getattr(household, "postal_code", ""),
                getattr(household, "address_line1", ""),
                getattr(household, "address_line2", ""),
                getattr(household, "address_line3", ""),
                getattr(profile, "mailing_postal_code", "") if profile is not None else "",
                getattr(profile, "mailing_address_line1", "") if profile is not None else "",
                getattr(profile, "mailing_address_line2", "") if profile is not None else "",
                getattr(district, "name", "") if district is not None else "",
                getattr(district, "short_name", "") if district is not None else "",
            ]
        )
    )
    return any(term in name_search_text for term in terms) and all(
        term in all_search_text for term in terms
    )


def handling_office_matches_candidate_address(
    *,
    handling_office_name: str,
    household: Any,
    profile: Any | None,
) -> bool:
    normalized_office = normalize_search_text(handling_office_name)
    if len(normalized_office) < 2:
        return False
    address_values = [
        getattr(household, "address_line1", ""),
        getattr(household, "address_line2", ""),
        getattr(household, "address_line3", ""),
    ]
    if profile is not None:
        address_values.extend(
            [
                getattr(profile, "mailing_address_line1", ""),
                getattr(profile, "mailing_address_line2", ""),
            ]
        )
    return any(
        normalized_office in normalize_search_text(value)
        for value in address_values
        if str(value or "").strip()
    )


def postal_scan_candidate_profile_is_relevant(profile: Any) -> bool:
    # A billing notice setting must not hide an actual incoming payment from
    # OCR matching.  The caller still decides whether the matched household is
    # receivable and which warning to show.
    del profile
    return True


def select_postal_scan_candidates(
    candidates: list[dict[str, Any]],
    *,
    limit: int = POSTAL_SCAN_MAX_CANDIDATES,
) -> list[dict[str, Any]]:
    maximum = max(0, min(int(limit), POSTAL_SCAN_MAX_CANDIDATES))
    if maximum == 0:
        return []
    ordered = sorted(
        (dict(candidate) for candidate in candidates),
        key=lambda candidate: -_candidate_score_value(candidate),
    )
    if not ordered:
        return []
    if _candidate_score_value(ordered[0]) >= POSTAL_SCAN_STRONG_CANDIDATE_SCORE:
        ordered = [
            candidate
            for candidate in ordered
            if _candidate_score_value(candidate) >= POSTAL_SCAN_PLAUSIBLE_ALTERNATIVE_SCORE
        ]
    return ordered[:maximum]


def _candidate_score_value(candidate: dict[str, Any]) -> int:
    try:
        return int(candidate.get("score") or 0)
    except (TypeError, ValueError):
        return 0


def candidate_name_match(normalized_query: str, name: str, kana: str) -> tuple[int, str]:
    if not normalized_query:
        return 0, ""
    normalized_name = normalize_search_text(name)
    normalized_kana = normalize_search_text(kana)
    if normalized_name and normalized_name == normalized_query:
        return 100, "氏名"
    if normalized_name and (normalized_name in normalized_query or normalized_query in normalized_name):
        return (92 if len(normalized_query) >= 2 else 70), "氏名"
    if normalized_kana and (normalized_kana == normalized_query):
        return 88, "氏名"
    if normalized_kana and (normalized_kana in normalized_query or normalized_query in normalized_kana):
        return (78 if len(normalized_query) >= 2 else 55), "氏名"
    fuzzy_name_score = fuzzy_text_score(normalized_query, normalized_name)
    if fuzzy_name_score:
        return fuzzy_name_score, "氏名類似"
    fuzzy_kana_score = fuzzy_text_score(normalized_query, normalized_kana)
    if fuzzy_kana_score >= 70:
        return min(fuzzy_kana_score, 76), "氏名類似"
    return 0, ""


def fuzzy_text_score(left: str, right: str) -> int:
    if not left or not right or min(len(left), len(right)) < 3:
        return 0
    distance = bounded_levenshtein_distance(left, right, max_distance=2)
    if distance == 1:
        return 82
    if distance == 2 and min(len(left), len(right)) >= 4:
        return 58
    ratio = SequenceMatcher(None, left, right).ratio()
    if ratio >= 0.82:
        return 74
    if ratio >= 0.62 and min(len(left), len(right)) >= 4:
        return 58
    return 0


def dedupe_text_list(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def normalize_phone(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", (value or "").strip())
    return re.sub(r"[^0-9]", "", normalized)


def normalize_phone_numbers(value: str | None) -> list[str]:
    normalized = unicodedata.normalize("NFKC", (value or "").strip())
    numbers = []
    for chunk in re.split(r"[/／,、;；\s]+", normalized):
        digits = re.sub(r"[^0-9]", "", chunk)
        if len(digits) >= 8:
            numbers.append(digits)
    if not numbers:
        digits = normalize_phone(normalized)
        if len(digits) >= 8:
            numbers.append(digits)
    return dedupe_text_list(numbers)


def candidate_phone_numbers(*, household: Any, profile: Any | None) -> list[str]:
    numbers: list[str] = []
    for value in [
        household.phone,
        household.mobile,
        profile.mailing_phone if profile is not None else "",
    ]:
        numbers.extend(normalize_phone_numbers(value))
    return dedupe_text_list(numbers)


def phone_numbers_are_similar(left: str, right: str) -> bool:
    if len(left) < 8 or len(right) < 8:
        return False
    if left == right:
        return True
    if len(left) == len(right):
        distance = bounded_levenshtein_distance(left, right, max_distance=2)
        if distance <= 1:
            return True
        if distance <= 2 and {left[0], right[0]} == {"0", "8"}:
            return True
    return phone_suffix_is_similar(left, right)


def phone_suffix_is_similar(left: str, right: str) -> bool:
    for suffix_length in [8, 7, 6]:
        if len(left) < suffix_length or len(right) < suffix_length:
            continue
        if bounded_levenshtein_distance(left[-suffix_length:], right[-suffix_length:], max_distance=1) <= 1:
            return True
    return False


def bounded_levenshtein_distance(left: str, right: str, *, max_distance: int) -> int:
    if abs(len(left) - len(right)) > max_distance:
        return max_distance + 1
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        row_min = current[0]
        for right_index, right_char in enumerate(right, start=1):
            insert_cost = current[right_index - 1] + 1
            delete_cost = previous[right_index] + 1
            replace_cost = previous[right_index - 1] + (left_char != right_char)
            value = min(insert_cost, delete_cost, replace_cost)
            current.append(value)
            row_min = min(row_min, value)
        if row_min > max_distance:
            return max_distance + 1
        previous = current
    return previous[-1]


def normalize_postal_code(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", (value or "").strip())
    match = re.search(r"(\d{3})\D*(\d{4})", normalized)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    digits = re.sub(r"[^0-9]", "", normalized)
    return digits[:7] if len(digits) >= 7 else digits


def address_match_for_ocr(
    *,
    ocr_address: str,
    normalized_ocr_address: str,
    household: Any,
    profile: Any | None,
) -> tuple[int, str]:
    if not normalized_ocr_address:
        return 0, ""
    address_scores = [
        address_score_for_text(
            ocr_address=ocr_address,
            normalized_ocr_address=normalized_ocr_address,
            stored_address=join_nonempty(
                [
                    household.postal_code,
                    household.address_line1,
                    household.address_line2,
                    household.address_line3,
                ]
            ),
        ),
        address_score_for_text(
            ocr_address=ocr_address,
            normalized_ocr_address=normalized_ocr_address,
            stored_address=join_nonempty(
                [
                    household.address_line1,
                    household.address_line2,
                    household.address_line3,
                ]
            ),
        ),
    ]
    if profile is not None:
        address_scores.extend(
            [
                address_score_for_text(
                    ocr_address=ocr_address,
                    normalized_ocr_address=normalized_ocr_address,
                    stored_address=join_nonempty(
                        [
                            profile.mailing_postal_code,
                            profile.mailing_address_line1,
                            profile.mailing_address_line2,
                        ]
                    ),
                ),
                address_score_for_text(
                    ocr_address=ocr_address,
                    normalized_ocr_address=normalized_ocr_address,
                    stored_address=join_nonempty(
                        [
                            profile.mailing_address_line1,
                            profile.mailing_address_line2,
                        ]
                    ),
                ),
            ]
        )
    score = max(address_scores)
    if score >= 40:
        return score, "住所" if score == 40 else "住所類似"
    return 0, ""


def address_score_for_text(
    *,
    ocr_address: str,
    normalized_ocr_address: str,
    stored_address: str,
) -> int:
    normalized_stored_address = normalize_search_text(stored_address)
    if not normalized_stored_address:
        return 0
    if len(normalized_ocr_address) >= 6 and normalized_ocr_address in normalized_stored_address:
        return 40
    if len(normalized_stored_address) >= 6 and normalized_stored_address in normalized_ocr_address:
        return 40

    ocr_number_tokens = set(address_number_tokens(ocr_address or normalized_ocr_address))
    stored_number_tokens = set(address_number_tokens(stored_address))
    shared_number_tokens = {
        token for token in ocr_number_tokens & stored_number_tokens if len(token) >= 2
    }
    if not shared_number_tokens:
        return 0

    ocr_text = address_text_without_numbers(normalized_ocr_address)
    stored_text = address_text_without_numbers(normalized_stored_address)
    text_similarity = SequenceMatcher(None, ocr_text, stored_text).ratio() if ocr_text and stored_text else 0
    has_long_number = any(len(token) >= 3 for token in shared_number_tokens)
    has_multiple_numbers = len(shared_number_tokens) >= 2
    if has_long_number and has_multiple_numbers and text_similarity >= 0.34:
        return 46
    if has_long_number and text_similarity >= 0.46:
        return 42
    if longest_common_substring_length(normalized_ocr_address, normalized_stored_address) >= 6:
        return 40
    return 0


def address_number_tokens(value: str | None) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value or "")
    return [match.group(0) for match in re.finditer(r"\d+", normalized)]


def address_text_without_numbers(value: str) -> str:
    return re.sub(r"\d+", "", value)


def longest_common_substring_length(left: str, right: str) -> int:
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    best = 0
    for left_char in left:
        current = [0]
        for right_index, right_char in enumerate(right, start=1):
            value = previous[right_index - 1] + 1 if left_char == right_char else 0
            current.append(value)
            best = max(best, value)
        previous = current
    return best


def normalize_search_text(value: str | None) -> str:
    cleaned = unicodedata.normalize("NFKC", (value or "").strip())
    chars = []
    for char in cleaned:
        code = ord(char)
        if 0x30A1 <= code <= 0x30F6:
            chars.append(chr(code - 0x60))
        elif char.isspace() or char in {"-", "ｰ", "－", "―", "_"}:
            continue
        else:
            chars.append(char.lower())
    return "".join(chars)


__all__ = [
    "POSTAL_SCAN_MAX_CANDIDATES",
    "POSTAL_SCAN_PLAUSIBLE_ALTERNATIVE_SCORE",
    "POSTAL_SCAN_STRONG_CANDIDATE_SCORE",
    "address_match_for_ocr",
    "address_number_tokens",
    "address_score_for_text",
    "address_text_without_numbers",
    "bounded_levenshtein_distance",
    "candidate_name_match",
    "candidate_phone_numbers",
    "candidate_score_for_scan",
    "dedupe_text_list",
    "fuzzy_text_score",
    "handling_office_matches_candidate_address",
    "join_nonempty",
    "longest_common_substring_length",
    "multi_term_query_matches_candidate",
    "normalize_phone",
    "normalize_phone_numbers",
    "normalize_postal_code",
    "normalize_search_text",
    "ocr_search_terms",
    "phone_numbers_are_similar",
    "phone_suffix_is_similar",
    "postal_scan_candidate_profile_is_relevant",
    "query_search_terms",
    "select_postal_scan_candidates",
]
