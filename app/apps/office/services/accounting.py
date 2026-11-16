from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from apps.imports import canonical_population
from apps.imports.models import ImportBatch, OfferingPayment, ServiceSchedule
from apps.office.services.memorials import _compact_service_label
from apps.office.services.offering_payments import (
    build_offering_payment_entry,
    linked_schedules_by_group,
    payment_sort_key,
)


def build_accounting_context(
    *,
    source_id: str,
    batch: ImportBatch,
    year: int,
    current_url: str,
    payment_categories: tuple[str, ...] | None = None,
) -> dict:
    provenance_batch = _canonical_accounting_provenance_batch(
        batch,
        source_id=source_id,
    )
    active_payment_categories = _resolved_payment_categories(payment_categories)
    payments = list(
        OfferingPayment.objects.filter(
            received_on__year=year,
            payment_category__in=active_payment_categories,
        )
        .select_related("household", "person", "service_schedule")
        .order_by("received_on", "id")
    )
    context = _build_accounting_period_context(
        batch=provenance_batch,
        year=year,
        payments=payments,
        current_url=current_url,
        active_payment_categories=active_payment_categories,
    )
    context.update(
        {
            "selected_source_id": source_id,
            "available_years": _available_accounting_years(
                provenance_batch,
                year,
                payment_categories=active_payment_categories,
            ),
            "batch_snapshot_id": provenance_batch.prepared_snapshot_id or "",
            "current_url": current_url,
            "show_year_form": True,
            "summary_period_label": "入金がある月",
            "summary_period_value": context["nonzero_month_count"],
        }
    )
    return context


def build_multi_year_accounting_context(
    *,
    source_id: str,
    batch: ImportBatch,
    current_url: str,
    payment_categories: tuple[str, ...] | None = None,
) -> dict:
    provenance_batch = _canonical_accounting_provenance_batch(
        batch,
        source_id=source_id,
    )
    active_payment_categories = _resolved_payment_categories(payment_categories)
    payments = list(
        OfferingPayment.objects.filter(
            payment_category__in=active_payment_categories,
        )
        .select_related("household", "person", "service_schedule")
        .order_by("received_on", "id")
    )
    years = sorted({payment.received_on.year for payment in payments}, reverse=True)
    year_groups = [
        _build_accounting_period_context(
            batch=provenance_batch,
            year=year,
            payments=[payment for payment in payments if payment.received_on.year == year],
            current_url=current_url,
            active_payment_categories=active_payment_categories,
        )
        for year in years
    ]
    annual_category_totals = _build_annual_category_totals(active_payment_categories)
    overall_total = Decimal("0")
    for payment in payments:
        amount = payment.amount or Decimal("0")
        overall_total += amount
        category_totals = annual_category_totals[payment.payment_category]
        category_totals["payment_count"] += 1
        category_totals["total_amount"] += amount
    return {
        "selected_source_id": source_id,
        "payment_count": len(payments),
        "annual_total": overall_total,
        "annual_categories": _present_category_totals(annual_category_totals),
        "year_groups": year_groups,
        "months": [],
        "nonzero_month_count": len(year_groups),
        "batch_snapshot_id": provenance_batch.prepared_snapshot_id or "",
        "current_url": current_url,
        "show_year_form": False,
        "summary_period_label": "対象年数",
        "summary_period_value": len(year_groups),
    }


def _build_accounting_period_context(
    *,
    batch: ImportBatch,
    year: int,
    payments: list[OfferingPayment],
    current_url: str,
    active_payment_categories: tuple[str, ...],
) -> dict:
    payments = sorted(payments, key=payment_sort_key)
    linked_schedule_groups = linked_schedules_by_group(
        batch,
        payments,
        canonical_population_checked=True,
    )
    period_entries: list[dict] = []
    months = [
        {
            "month": month,
            "label": f"{year}年{month}月",
            "payment_count": 0,
            "total_amount": Decimal("0"),
            "entries": [],
        }
        for month in range(1, 13)
    ]
    annual_total = Decimal("0")
    annual_category_totals = _build_annual_category_totals(active_payment_categories)

    for payment in payments:
        month_row = months[payment.received_on.month - 1]
        amount = payment.amount or Decimal("0")
        linked_service_items = _payment_linked_service_items(
            payment,
            linked_schedule_groups,
        )
        month_row["payment_count"] += 1
        month_row["total_amount"] += amount
        entry = build_offering_payment_entry(
            payment,
            current_url=current_url,
            linked_service_items=linked_service_items,
        )
        entry["household_name"] = _compact_accounting_name(entry.get("household_name"))
        if not entry["is_temple_event"]:
            entry["person_name"] = _compact_accounting_name(entry.get("person_name"))
        entry["person_label"] = entry["person_name"]
        entry["service_label"] = _accounting_service_display_label(payment)
        period_entries.append(entry)
        month_row["entries"].append(entry)
        annual_total += amount
        category_totals = annual_category_totals[payment.payment_category]
        category_totals["payment_count"] += 1
        category_totals["total_amount"] += amount

    current_year_month = _current_year_month()
    display_months = [
        month
        for month in reversed(months)
        if month["payment_count"] or (year, month["month"]) <= current_year_month
    ]

    return {
        "year": year,
        "label": f"{year}年",
        "entries": period_entries,
        "months": display_months,
        "payment_count": len(payments),
        "annual_total": annual_total,
        "nonzero_month_count": sum(1 for month in months if month["payment_count"]),
        "annual_categories": _present_category_totals(annual_category_totals),
    }


def _current_year_month() -> tuple[int, int]:
    today = timezone.localdate()
    return today.year, today.month


def _build_annual_category_totals(active_payment_categories: tuple[str, ...]) -> dict[str, dict]:
    return {
        value: {
            "label": label,
            "payment_count": 0,
            "total_amount": Decimal("0"),
        }
        for value, label in OfferingPayment.Category.choices
        if value in active_payment_categories
    }


def _present_category_totals(annual_category_totals: dict[str, dict]) -> list[dict]:
    return [
        item
        for value, _label in OfferingPayment.Category.choices
        if value in annual_category_totals
        for item in [annual_category_totals[value]]
        if item["payment_count"]
    ]


def _payment_linked_service_items(
    payment: OfferingPayment,
    linked_schedules_by_group: dict[str, list[ServiceSchedule]],
) -> list[str]:
    if (
        not payment.service_schedule_id
        or payment.service_schedule is None
        or not payment.service_schedule.link_group_key
    ):
        return []
    linked = [
        item
        for item in linked_schedules_by_group.get(payment.service_schedule.link_group_key, [])
        if item.pk != payment.service_schedule_id
    ]
    if not linked:
        return []
    return [
        f"{_compact_accounting_name(item.subject_name or item.person_name_snapshot or item.person_uid)} "
        f"{_accounting_service_display_label_for_schedule(item)}"
        for item in linked
    ]


def _compact_accounting_name(value: object) -> str:
    return "".join(str(value or "").split())


def _compact_accounting_service_label(value: object) -> str:
    compact_label = _compact_service_label(str(value or "").strip())
    if compact_label == "一周忌":
        return "1周忌"
    return compact_label


def _accounting_service_display_label(payment: OfferingPayment) -> str:
    schedule = payment.service_schedule if payment.service_schedule_id and payment.service_schedule is not None else None
    if schedule is None:
        return "法要外"
    return _accounting_service_display_label_for_schedule(schedule)


def _accounting_service_display_label_for_schedule(schedule: ServiceSchedule) -> str:
    if schedule.event_scope == ServiceSchedule.EventScope.TEMPLE:
        return schedule.service_label
    if (
        str(schedule.category or "").strip() == ServiceSchedule.Category.OTHER
        and str(schedule.service_label or "").strip() != "葬儀"
    ):
        return "その他"
    return _compact_accounting_service_label(schedule.service_label)


def _available_accounting_years(
    batch: ImportBatch,
    year: int,
    *,
    payment_categories: tuple[str, ...],
) -> list[int]:
    del batch
    year_candidates = {year - 1, year, year + 1}
    year_candidates.update(
        item.year
        for item in OfferingPayment.objects.filter(
            payment_category__in=payment_categories,
        ).dates("received_on", "year")
    )
    return sorted((candidate for candidate in year_candidates if candidate > 0), reverse=True)


def _resolved_payment_categories(payment_categories: tuple[str, ...] | None) -> tuple[str, ...]:
    if payment_categories:
        return payment_categories
    return tuple(value for value, _label in OfferingPayment.Category.choices)


def _canonical_accounting_provenance_batch(
    fallback_batch: ImportBatch,
    *,
    source_id: str,
) -> ImportBatch:
    """Resolve display metadata without using batch as the accounting scope."""

    return (
        canonical_population.canonical_provenance_import_batch(source_id=source_id)
        or fallback_batch
    )
