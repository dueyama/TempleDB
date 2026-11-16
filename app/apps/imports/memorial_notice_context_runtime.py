from __future__ import annotations

from datetime import date

from django.db.utils import OperationalError, ProgrammingError

from apps.core.services import memorial_dates

from . import canonical_population, service_ledger_runtime
from .household_memorial_candidates_runtime import (
    _build_memorial_candidates,
    _notice_eligible_memorial_members,
)
from .memorial_notice_layout import (
    _blank_memorial_notice_entry,
    _memorial_notice_table_entries,
    _memorial_notice_table_rows,
    _pad_memorial_notice_columns,
    _pad_memorial_notice_entries,
    _reference_heading_memorial_notice_entry,
)
from .models import ServiceSchedule
from .runtime_shared import _int_sort, _sort_text


def _runtime_module():
    from . import memorial_notice_runtime

    return memorial_notice_runtime


def build_memorial_notice_context(
    source_id: str | None = None,
    *,
    year: int | None = None,
    include_reference_year: bool = True,
    intro_text: str | None = None,
    outro_text: str | None = None,
    signature_text: str | None = None,
    recipient_font_size: float | None = None,
    body_font_size: float | None = None,
    signature_font_size: float | None = None,
    table_font_size: float | None = None,
    data_backend: str = "db",
) -> dict:
    return _legacy_build_memorial_notice_context(
        source_id=source_id,
        year=year,
        include_reference_year=include_reference_year,
        intro_text=intro_text,
        outro_text=outro_text,
        signature_text=signature_text,
        recipient_font_size=recipient_font_size,
        body_font_size=body_font_size,
        signature_font_size=signature_font_size,
        table_font_size=table_font_size,
        data_backend=data_backend,
    )


def _resolved_memorial_notice_target_year(year: int | None) -> int:
    return year if isinstance(year, int) and 1900 <= year <= 2100 else date.today().year + 1


def _household_ids_with_memorial_notice_targets(
    source_id: str | None = None,
    *,
    year: int | None = None,
) -> set[str]:
    runtime = _runtime_module()
    active_source_id = (source_id or "").strip() or runtime.resolve_runtime_source_entry()["source_id"]
    target_year = _resolved_memorial_notice_target_year(year)
    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    if provenance_batch is None:
        return set()
    dataset = runtime._load_household_browser_dataset(
        active_source_id,
        provenance_batch.prepared_snapshot_id or "",
    )
    memorial_rules = memorial_dates._effective_memorial_rules(dataset.get("memorial_rules", []))
    period_start = date(target_year, 1, 1)
    period_end = date(target_year, 12, 31)
    household_ids: set[str] = set()
    for household_id, detail in dataset.get("household_details", {}).items():
        notice_members = _notice_eligible_memorial_members(detail)
        if not notice_members:
            continue
        candidates = [
            candidate
            for candidate in _build_memorial_candidates(
                notice_members,
                memorial_rules,
                period_start,
                period_end,
            )
            if candidate.get("candidate_type") == "回忌"
        ]
        if candidates:
            household_ids.add(household_id)
    return household_ids


def _legacy_build_memorial_notice_context(
    source_id: str | None = None,
    *,
    year: int | None = None,
    include_reference_year: bool = True,
    intro_text: str | None = None,
    outro_text: str | None = None,
    signature_text: str | None = None,
    recipient_font_size: float | None = None,
    body_font_size: float | None = None,
    signature_font_size: float | None = None,
    table_font_size: float | None = None,
    data_backend: str = "db",
) -> dict:
    del source_id, data_backend
    runtime = _runtime_module()
    source = runtime.resolve_runtime_source_entry()
    active_source_id = source["source_id"]
    target_year = _resolved_memorial_notice_target_year(year)
    saved_template = runtime._get_saved_memorial_notice_template(active_source_id, target_year)
    target_year_with_wareki = f"{target_year}（{memorial_dates._to_wareki_year_numeric(target_year)}）年"
    replacement_values = runtime._memorial_notice_template_values(target_year, target_year_with_wareki)
    token_rows = runtime._memorial_notice_template_token_rows(replacement_values)
    policy_defaults = runtime._effective_memorial_notice_defaults()
    raw_intro_text = (
        intro_text
        if intro_text is not None
        else (
            saved_template.intro_text
            if saved_template is not None
            else policy_defaults["intro_text"]
        )
    )
    raw_outro_text = (
        outro_text
        if outro_text is not None
        else (
            saved_template.outro_text
            if saved_template is not None
            else policy_defaults["outro_text"]
        )
    )
    raw_signature_text = (
        signature_text
        if signature_text is not None
        else (
            saved_template.signature_text
            if saved_template is not None
            else policy_defaults["signature_text"]
        )
    )
    resolved_intro_text = runtime._render_memorial_notice_template_text(raw_intro_text, replacement_values)
    resolved_outro_text = runtime._render_memorial_notice_template_text(raw_outro_text, replacement_values)
    resolved_signature_text = runtime._render_memorial_notice_template_text(
        raw_signature_text,
        replacement_values,
    )
    resolved_style = {
        "recipient_font_size": runtime._resolve_memorial_notice_style_value(
            recipient_font_size,
            saved_template.recipient_font_size if saved_template is not None else None,
            runtime.DEFAULT_MEMORIAL_NOTICE_STYLE["recipient_font_size"],
        ),
        "body_font_size": runtime._resolve_memorial_notice_style_value(
            body_font_size,
            saved_template.body_font_size if saved_template is not None else None,
            runtime.DEFAULT_MEMORIAL_NOTICE_STYLE["body_font_size"],
        ),
        "signature_font_size": runtime._resolve_memorial_notice_style_value(
            signature_font_size,
            saved_template.signature_font_size if saved_template is not None else None,
            runtime.DEFAULT_MEMORIAL_NOTICE_STYLE["signature_font_size"],
        ),
        "table_font_size": runtime._resolve_memorial_notice_style_value(
            table_font_size,
            saved_template.table_font_size if saved_template is not None else None,
            runtime.DEFAULT_MEMORIAL_NOTICE_STYLE["table_font_size"],
        ),
    }
    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    latest_export = runtime.latest_export_snapshot(active_source_id)
    if provenance_batch is None:
        return {
            "available": False,
            "selected_source_id": active_source_id,
            "message": "現行データがまだありません。",
            "data_backend": "db",
            "target_year": target_year,
            "target_year_with_wareki": target_year_with_wareki,
            "include_reference_year": include_reference_year,
            "memorial_notice_template_tokens": token_rows,
            "intro_text_input": raw_intro_text,
            "outro_text_input": raw_outro_text,
            "signature_text_input": raw_signature_text,
            "intro_text": resolved_intro_text,
            "outro_text": resolved_outro_text,
            "signature_text": resolved_signature_text,
            "notice_style": resolved_style,
            "template_saved": saved_template is not None,
            "template_saved_at": saved_template.updated_at if saved_template is not None else None,
            "latest_export": latest_export,
            "canonical_snapshot_id": "",
        }

    canonical_snapshot_id = provenance_batch.prepared_snapshot_id or ""
    dataset = runtime._load_household_browser_dataset(active_source_id, canonical_snapshot_id)
    memorial_rules = memorial_dates._effective_memorial_rules(dataset.get("memorial_rules", []))
    period_start = date(target_year, 1, 1)
    period_end = date(target_year, 12, 31)

    actual_schedules_by_household: dict[str, list[ServiceSchedule]] = {}
    linked_schedules_by_group: dict[str, list[ServiceSchedule]] = {}
    if dataset["data_backend"] == "db":
        try:
            schedules = list(
                ServiceSchedule.objects.filter(
                    deleted_at__isnull=True,
                )
                .exclude(
                    record_origin=ServiceSchedule.Origin.IMPORTED,
                    source_table__in=runtime.LEGACY_IMPORTED_SCHEDULE_SOURCE_TABLES,
                )
                .select_related("person", "household")
                .order_by("scheduled_date", "completed_on", "target_date", "id")
            )
        except (OperationalError, ProgrammingError):
            schedules = []
        for schedule in schedules:
            if not service_ledger_runtime._is_actual_service_schedule(schedule):
                continue
            actual_schedules_by_household.setdefault(schedule.household_uid, []).append(schedule)
            if schedule.link_group_key:
                linked_schedules_by_group.setdefault(schedule.link_group_key, []).append(schedule)

    household_packets: list[dict] = []
    for household_id, detail in sorted(
        dataset["household_details"].items(),
        key=lambda item: (
            _sort_text(item[1]["summary"].get("kana")),
            _sort_text(item[1]["summary"].get("name")),
            _int_sort(item[0]),
        ),
    ):
        notice_members = _notice_eligible_memorial_members(detail)
        candidates = [
            candidate
            for candidate in _build_memorial_candidates(
                notice_members,
                memorial_rules,
                period_start,
                period_end,
            )
            if candidate.get("candidate_type") == "回忌"
        ]
        if not candidates:
            continue
        notice_columns = [
            runtime._build_memorial_notice_column(
                candidate,
                actual_schedules_by_household.get(household_id, []),
                linked_schedules_by_group,
            )
            for candidate in candidates
        ]
        if not notice_columns:
            continue
        reference_year = target_year + 1
        reference_columns: list[dict] = []
        if include_reference_year:
            reference_candidates = [
                candidate
                for candidate in _build_memorial_candidates(
                    notice_members,
                    memorial_rules,
                    date(reference_year, 1, 1),
                    date(reference_year, 12, 31),
                )
                if candidate.get("candidate_type") == "回忌"
            ]
            reference_columns = [
                runtime._build_memorial_notice_column(
                    candidate,
                    actual_schedules_by_household.get(household_id, []),
                    linked_schedules_by_group,
                )
                for candidate in reference_candidates
            ]
        pages = []
        reference_entries = _memorial_notice_table_entries(reference_columns)
        notice_chunks = list(memorial_dates._chunked(notice_columns, runtime.MEMORIAL_NOTICE_ROWS_PER_PAGE))
        for index, chunk in enumerate(notice_chunks, start=1):
            padded_chunk = _pad_memorial_notice_columns(chunk, runtime.MEMORIAL_NOTICE_ROWS_PER_PAGE)
            display_entries = _memorial_notice_table_entries(chunk)
            if index == len(notice_chunks) and reference_entries:
                remaining_slots = runtime.MEMORIAL_NOTICE_ROWS_PER_PAGE - len(display_entries)
                if remaining_slots >= 3:
                    reference_take = min(len(reference_entries), remaining_slots - 2)
                    display_entries.extend(
                        [
                            _blank_memorial_notice_entry(),
                            _reference_heading_memorial_notice_entry(reference_year),
                            *reference_entries[:reference_take],
                        ]
                    )
                    reference_entries = reference_entries[reference_take:]
            pages.append(
                {
                    "column_count": runtime.MEMORIAL_NOTICE_ROWS_PER_PAGE,
                    "table_entries": _pad_memorial_notice_entries(
                        display_entries,
                        runtime.MEMORIAL_NOTICE_ROWS_PER_PAGE,
                    ),
                    "table_rows": _memorial_notice_table_rows(padded_chunk),
                }
            )
        while reference_entries:
            reference_take = min(len(reference_entries), runtime.MEMORIAL_NOTICE_ROWS_PER_PAGE - 1)
            display_entries = [
                _reference_heading_memorial_notice_entry(reference_year),
                *reference_entries[:reference_take],
            ]
            reference_entries = reference_entries[reference_take:]
            pages.append(
                {
                    "column_count": runtime.MEMORIAL_NOTICE_ROWS_PER_PAGE,
                    "table_entries": _pad_memorial_notice_entries(
                        display_entries,
                        runtime.MEMORIAL_NOTICE_ROWS_PER_PAGE,
                    ),
                    "table_rows": [],
                }
            )
        page_count = len(pages)
        for index, page in enumerate(pages, start=1):
            page["page_number"] = index
            page["page_count"] = page_count
            page["reference_year"] = reference_year
        household_packets.append(
            {
                "household": detail["summary"],
                "recipient_name": detail["summary"].get("name") or detail["summary"].get("household_id"),
                "pages": pages,
                "column_count": len(notice_columns),
            }
        )

    page_documents = [
        {
            **packet,
            **page,
        }
        for packet in household_packets
        for page in packet["pages"]
    ]

    return {
        "available": bool(page_documents),
        "selected_source_id": active_source_id,
        "source": runtime.source_summary(active_source_id),
        "latest_export": latest_export,
        "canonical_snapshot_id": canonical_snapshot_id,
        "target_year": target_year,
        "target_year_label": f"{target_year}年",
        "target_year_with_wareki": target_year_with_wareki,
        "include_reference_year": include_reference_year,
        "memorial_notice_template_tokens": token_rows,
        "intro_text_input": raw_intro_text,
        "outro_text_input": raw_outro_text,
        "signature_text_input": raw_signature_text,
        "intro_text": resolved_intro_text,
        "outro_text": resolved_outro_text,
        "signature_text": resolved_signature_text,
        "notice_style": resolved_style,
        "template_saved": saved_template is not None,
        "template_saved_at": saved_template.updated_at if saved_template is not None else None,
        "documents": page_documents,
        "household_count": len(household_packets),
        "page_count": len(page_documents),
        "data_backend": dataset["data_backend"],
        "message": (
            ""
            if page_documents
            else f"{target_year}年1月から12月に回忌法要がある家は見つかりませんでした。"
        ),
    }
