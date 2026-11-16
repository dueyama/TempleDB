from __future__ import annotations

from apps.core.services import tenant_policy

from .data_science_analysis import (
    _cohort_mode_label,
    _cohort_mode_options,
    _normalize_cohort_mode,
)
from .data_science_charts import _matplotlib_font_name
from .data_science_context_charts import _build_data_science_chart_payloads
from .data_science_context_dataset import _resolved_data_science_dataset_context
from .data_science_context_metrics import _build_data_science_metric_payload
from .data_science_shared import completeness_color_map, completeness_labels


def _empty_data_science_context(
    *,
    active_source_id: str,
    month_cohort_mode: str,
    age_cohort_mode: str,
    source_summary_payload: dict,
    message: str = "検索対象の現行台帳が見つかりません。",
) -> dict:
    return {
        "available": False,
        "selected_source_id": active_source_id,
        "selected_month_cohort_mode": month_cohort_mode,
        "month_cohort_mode_label": _cohort_mode_label(month_cohort_mode),
        "month_cohort_mode_options": _cohort_mode_options(month_cohort_mode),
        "selected_age_cohort_mode": age_cohort_mode,
        "age_cohort_mode_label": _cohort_mode_label(age_cohort_mode),
        "age_cohort_mode_options": _cohort_mode_options(age_cohort_mode),
        "source": source_summary_payload,
        "message": message,
        "data_backend": "db",
    }


def _build_data_science_context_payload(
    source_id: str | None = None,
    month_cohort_mode: str | None = None,
    age_cohort_mode: str | None = None,
    data_backend: str = "db",
) -> dict:
    data_science_copy = tenant_policy.terminology_copy()["data_science"]
    active_completeness_labels = completeness_labels()
    active_completeness_color_map = completeness_color_map()
    dataset_context = _resolved_data_science_dataset_context(
        source_id=source_id,
        data_backend=data_backend,
    )
    active_source_id = dataset_context["active_source_id"]
    source_summary_payload = dataset_context["source_summary"]
    registered_sources_payload = dataset_context["registered_sources"]
    latest_export = dataset_context["latest_export"]
    canonical_batch = dataset_context.get("canonical_batch")
    canonical_snapshot_id = dataset_context.get("canonical_snapshot_id", "")
    active_month_cohort_mode = _normalize_cohort_mode(month_cohort_mode)
    active_age_cohort_mode = _normalize_cohort_mode(age_cohort_mode)
    dataset_error = dataset_context.get("dataset_error", "")
    if dataset_error or dataset_context.get("dataset") is None:
        return _empty_data_science_context(
            active_source_id=active_source_id,
            month_cohort_mode=active_month_cohort_mode,
            age_cohort_mode=active_age_cohort_mode,
            source_summary_payload=source_summary_payload,
            message=dataset_error or "DB の過去帳データを読み出せませんでした。",
        )

    dataset = dataset_context["dataset"]
    metrics = _build_data_science_metric_payload(
        dataset,
        month_cohort_mode=active_month_cohort_mode,
        age_cohort_mode=active_age_cohort_mode,
    )
    charts = _build_data_science_chart_payloads(
        metrics,
        month_cohort_mode=active_month_cohort_mode,
        age_cohort_mode=active_age_cohort_mode,
        active_completeness_labels=active_completeness_labels,
        active_completeness_color_map=active_completeness_color_map,
        data_science_copy=data_science_copy,
    )
    return {
        "available": True,
        "selected_source_id": active_source_id,
        "selected_month_cohort_mode": active_month_cohort_mode,
        "month_cohort_mode_label": _cohort_mode_label(active_month_cohort_mode),
        "month_cohort_mode_options": _cohort_mode_options(active_month_cohort_mode),
        "selected_age_cohort_mode": active_age_cohort_mode,
        "age_cohort_mode_label": _cohort_mode_label(active_age_cohort_mode),
        "age_cohort_mode_options": _cohort_mode_options(active_age_cohort_mode),
        "data_backend": dataset["data_backend"],
        "registered_sources": registered_sources_payload,
        "source": source_summary_payload,
        "latest_export": latest_export,
        "canonical_batch": canonical_batch,
        "canonical_snapshot_id": canonical_snapshot_id,
        "memorial_member_total": metrics["memorial_member_total"],
        "with_death_date_count": metrics["with_death_date_count"],
        "with_age_count": metrics["with_age_count"],
        "unparsed_death_date_count": metrics["unparsed_death_date_count"],
        "as_of_date": metrics["as_of_date"],
        "future_death_date_count": metrics["future_death_date_count"],
        "partial_year": metrics["partial_year"],
        "partial_year_count": metrics["partial_year_count"],
        "analysis_record_count": metrics["analysis_record_count"],
        "calendar_analysis_count": metrics["calendar_analysis_count"],
        "calendar_observation_start": metrics["calendar_observation_start"],
        "calendar_observation_end": metrics["calendar_observation_end"],
        "calendar_observation_day_count": metrics["calendar_observation_day_count"],
        "death_year_range": metrics["death_year_range"],
        "analysis_year_range": metrics["analysis_year_range"],
        "analysis_year_rule_label": metrics["analysis_year_rule_label"],
        "death_interval_stats": metrics["interval_distribution"]["stats"],
        "poisson_consistency": metrics["poisson_consistency"],
        "interval_survival_analysis": metrics["interval_survival_analysis"],
        "year_count_diagnostics": metrics["year_count_diagnostics"],
        "year_count_distribution": metrics["year_count_distribution"],
        "year_month_heatmap_analysis": metrics["year_month_heatmap_analysis"],
        "same_day_cluster_analysis": metrics["same_day_cluster_analysis"],
        "household_concentration_analysis": metrics["household_concentration_analysis"],
        "completeness_by_decade_analysis": metrics["completeness_by_decade_analysis"],
        "month_day_stats": metrics["month_day_distribution"]["stats"],
        "month_day_grid_rows": metrics["month_day_distribution"]["grid_rows"],
        "missing_month_day_groups": metrics["month_day_distribution"]["missing_groups"],
        "top_month_day_rows": metrics["month_day_distribution"]["top_days"],
        "month_day_details": metrics["month_day_details"],
        "death_year_details": metrics["death_year_details"],
        "death_decade_month_stats": metrics["death_decade_month_analysis"]["stats"],
        "death_decade_age_stats": metrics["death_decade_age_analysis"]["stats"],
        "average_age_trend_stats": metrics["average_age_trend_analysis"]["stats"],
        "annual_age_sum_trend_stats": metrics["annual_age_sum_trend_analysis"]["stats"],
        "month_day_bias_stats": metrics["month_day_bias_analysis"]["stats"],
        "month_day_bias_top_rows": metrics["month_day_bias_analysis"]["top_rows"],
        "month_day_overlap_distribution": metrics["month_day_overlap_distribution"],
        "homyo_ingo_stats": metrics["homyo_ingo_analysis"]["stats"],
        "homyo_ingo_rows": metrics["homyo_ingo_analysis"]["rows"],
        "homyo_ingo_type_rows": metrics["homyo_ingo_type_analysis"]["rows"],
        "homyo_stats": metrics["homyo_analysis"]["stats"],
        "homyo_top_rows": metrics["homyo_analysis"]["rows"],
        "historical_death_count": metrics["historical_death_count"],
        "historical_death_records": metrics["historical_death_records"],
        "charts": charts,
        "matplotlib_font_name": _matplotlib_font_name(),
        "death_month_rows": metrics["death_month_rows"],
        "death_year_rows": metrics["death_year_rows"],
        "age_bucket_rows": metrics["age_bucket_rows"],
        "top_households": metrics["top_households"],
    }
