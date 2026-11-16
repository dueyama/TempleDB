from __future__ import annotations

from datetime import date

from .data_science_analysis import (
    _age_bucket_label,
    _age_bucket_labels,
    _analysis_year_range,
    _analysis_year_rule_label,
    _annual_age_sum_trend_analysis,
    _average_age_trend_analysis,
    _completeness_by_decade_analysis,
    _death_decade_age_analysis,
    _death_decade_month_analysis,
    _death_interval_distribution,
    _death_year_details,
    _group_counts_by_gender,
    _homyo_character_analysis,
    _homyo_ingo_analysis,
    _homyo_ingo_type_analysis,
    _household_concentration_analysis,
    _interval_qq_analysis,
    _interval_survival_analysis,
    _memorial_members_dataframe,
    _month_day_bias_analysis,
    _month_day_details,
    _month_day_distribution,
    _month_day_overlap_distribution_analysis,
    _poisson_process_consistency_analysis,
    _same_day_cluster_analysis,
    _series_rows,
    _year_count_diagnostics,
    _year_count_distribution_analysis,
    _year_month_heatmap_analysis,
)
from .data_science_shared import WEEKDAYS_JA, _int_sort, _sort_text


def _historical_death_records_payload(records) -> list[dict]:
    return [
        {
            "death_date": row["death_date"].date().isoformat()
            if hasattr(row["death_date"], "date")
            else str(row["death_date"])[:10],
            "death_year": int(row["death_year"]),
            "name": row["name"],
            "person_id": row["person_id"],
            "household_id": row["household_id"],
            "household_name": row["household_name"],
        }
        for _, row in records.iterrows()
    ]


def _month_calendar_exposure_series(
    observation_start: date | None,
    observation_end: date,
):
    import pandas as pd

    month_labels = [f"{month}月" for month in range(1, 13)]
    if observation_start is None or observation_end < observation_start:
        return pd.Series([0] * 12, index=month_labels, dtype="float64")
    calendar_days = pd.date_range(observation_start, observation_end, freq="D")
    exposure = (
        pd.Series(calendar_days.month)
        .value_counts()
        .reindex(range(1, 13), fill_value=0)
        .sort_index()
        .astype("float64")
    )
    exposure.index = month_labels
    return exposure


def _weekday_calendar_exposure_series(
    observation_start: date | None,
    observation_end: date,
):
    import pandas as pd

    if observation_start is None or observation_end < observation_start:
        return pd.Series([0] * 7, index=WEEKDAYS_JA, dtype="float64")
    calendar_days = pd.date_range(observation_start, observation_end, freq="D")
    exposure_by_monday_index = (
        pd.Series(calendar_days.dayofweek)
        .value_counts()
        .reindex(range(7), fill_value=0)
        .astype("float64")
    )
    return pd.Series(
        {
            WEEKDAYS_JA[(monday_index + 1) % 7]: exposure_by_monday_index[monday_index]
            for monday_index in range(7)
        }
    ).reindex(WEEKDAYS_JA)


def _rates_per_thousand_calendar_days(series_map: dict, exposure_series) -> dict:
    return {
        label: (
            series.astype("float64")
            .div(exposure_series.where(exposure_series > 0))
            .mul(1000.0)
            .fillna(0.0)
            .round(3)
        )
        for label, series in series_map.items()
    }


def _build_data_science_metric_payload(
    dataset: dict,
    *,
    month_cohort_mode: str,
    age_cohort_mode: str,
    as_of_date: date | None = None,
) -> dict:
    import pandas as pd

    active_as_of_date = as_of_date or date.today()
    as_of_timestamp = pd.Timestamp(active_as_of_date)
    memorial_members = [
        member
        for detail in dataset["household_details"].values()
        for member in detail["memorial_members"]
    ]
    dataframe = _memorial_members_dataframe(memorial_members)
    parse_failed_dates = dataframe[
        dataframe["death_date_raw"].astype(str).ne("") & dataframe["death_date"].isna()
    ].copy()
    canonical_death_dates = dataframe[dataframe["death_date"].notna()].copy()
    future_death_dates = canonical_death_dates[
        canonical_death_dates["death_date"] > as_of_timestamp
    ].copy()
    with_death_date = canonical_death_dates[
        canonical_death_dates["death_date"] <= as_of_timestamp
    ].copy()
    with_age = dataframe[
        dataframe["age_at_death"].notna()
        & (dataframe["death_date"].isna() | (dataframe["death_date"] <= as_of_timestamp))
    ].copy()
    partial_year = active_as_of_date.year
    partial_year_count = int((with_death_date["death_year"] == partial_year).sum())
    completed_death_dates = with_death_date[
        with_death_date["death_year"] < partial_year
    ].copy()
    year_counts = with_death_date["death_year"].value_counts().sort_index()
    analysis_year_range = _analysis_year_range(completed_death_dates["death_year"])
    if analysis_year_range["start"] is not None:
        analysis_year_range["end"] = partial_year - 1
    if analysis_year_range["start"] is None:
        analysis_year_counts = year_counts.iloc[0:0]
        analysis_year_values: list[int] = []
        analysis_year_gender_counts = _group_counts_by_gender(
            with_death_date.iloc[0:0],
            "death_year",
            analysis_year_values,
            label_fn=str,
        )
    else:
        analysis_year_values = list(
            range(analysis_year_range["start"], analysis_year_range["end"] + 1)
        )
        analysis_year_counts = year_counts.reindex(analysis_year_values, fill_value=0)
        analysis_year_gender_counts = _group_counts_by_gender(
            with_death_date[with_death_date["death_year"].isin(analysis_year_values)],
            "death_year",
            analysis_year_values,
            label_fn=str,
        )
    if analysis_year_range["start"] is None:
        analysis_with_death_date = completed_death_dates.iloc[0:0]
    else:
        analysis_with_death_date = completed_death_dates[
            (completed_death_dates["death_year"] >= analysis_year_range["start"])
            & (completed_death_dates["death_year"] <= analysis_year_range["end"])
        ].copy()
    if analysis_year_range["start"] is None:
        if with_death_date.empty:
            calendar_observation_start = None
            calendar_death_dates = with_death_date.iloc[0:0]
        else:
            calendar_start_year = int(with_death_date["death_year"].min())
            calendar_observation_start = date(calendar_start_year, 1, 1)
            calendar_death_dates = with_death_date.copy()
    else:
        calendar_observation_start = date(analysis_year_range["start"], 1, 1)
        calendar_death_dates = with_death_date[
            with_death_date["death_date"] >= pd.Timestamp(calendar_observation_start)
        ].copy()
    calendar_month_exposure = _month_calendar_exposure_series(
        calendar_observation_start,
        active_as_of_date,
    )
    calendar_weekday_exposure = _weekday_calendar_exposure_series(
        calendar_observation_start,
        active_as_of_date,
    )
    calendar_observation_day_count = int(calendar_month_exposure.sum())
    month_counts = (
        calendar_death_dates["death_month"]
        .value_counts()
        .reindex(range(1, 13), fill_value=0)
        .sort_index()
    )
    month_day_distribution = _month_day_distribution(calendar_death_dates)
    month_day_distribution["stats"].update(
        {
            "record_count": int(len(calendar_death_dates)),
            "observation_start": calendar_observation_start.isoformat()
            if calendar_observation_start is not None
            else None,
            "observation_end": active_as_of_date.isoformat(),
        }
    )
    completed_month_day_distribution = _month_day_distribution(
        analysis_with_death_date
    )
    month_gender_counts = _group_counts_by_gender(
        calendar_death_dates,
        "death_month",
        range(1, 13),
        label_fn=lambda value: f"{value}月",
    )
    month_gender_rates = _rates_per_thousand_calendar_days(
        month_gender_counts,
        calendar_month_exposure,
    )
    weekday_gender_counts = _group_counts_by_gender(
        calendar_death_dates,
        "death_weekday_label",
        WEEKDAYS_JA,
    )
    weekday_gender_rates = _rates_per_thousand_calendar_days(
        weekday_gender_counts,
        calendar_weekday_exposure,
    )
    death_decade_month_analysis = _death_decade_month_analysis(
        with_death_date,
        start_year=analysis_year_range["start"],
        end_year=analysis_year_range["end"],
    )
    death_decade_age_analysis = _death_decade_age_analysis(
        with_age,
        start_year=analysis_year_range["start"],
        end_year=analysis_year_range["end"],
    )
    average_age_trend_analysis = _average_age_trend_analysis(
        with_age,
        start_year=analysis_year_range["start"],
        end_year=analysis_year_range["end"],
    )
    annual_age_sum_trend_analysis = _annual_age_sum_trend_analysis(
        with_age,
        start_year=analysis_year_range["start"],
        end_year=analysis_year_range["end"],
    )
    month_day_bias_analysis = _month_day_bias_analysis(
        month_day_distribution["matrix"],
        exposure_dataframe=calendar_death_dates,
        observation_start=calendar_observation_start,
        observation_end=active_as_of_date,
    )
    month_day_overlap_distribution = _month_day_overlap_distribution_analysis(
        completed_month_day_distribution["matrix"],
        exclude_february_29=True,
    )
    interval_distribution = _death_interval_distribution(
        analysis_with_death_date,
        start_year=analysis_year_range["start"],
    )
    poisson_consistency = _poisson_process_consistency_analysis(
        analysis_with_death_date,
        start_year=analysis_year_range["start"],
        end_year=analysis_year_range["end"],
        interval_stats=interval_distribution["stats"],
    )
    interval_survival_analysis = _interval_survival_analysis(
        interval_distribution["intervals"],
        mean_days=interval_distribution["stats"]["mean_days"],
    )
    interval_qq_analysis = _interval_qq_analysis(
        interval_distribution["intervals"],
        mean_days=interval_distribution["stats"]["mean_days"],
    )
    year_count_diagnostics = _year_count_diagnostics(analysis_year_counts)
    year_count_distribution = _year_count_distribution_analysis(analysis_year_counts)
    year_month_heatmap_analysis = _year_month_heatmap_analysis(
        with_death_date,
        start_year=analysis_year_range["start"],
        end_year=analysis_year_range["end"],
    )
    same_day_cluster_analysis = _same_day_cluster_analysis(
        with_death_date,
        start_year=analysis_year_range["start"],
        end_year=analysis_year_range["end"],
    )
    completeness_by_decade_analysis = _completeness_by_decade_analysis(
        with_death_date,
        start_year=analysis_year_range["start"],
        end_year=analysis_year_range["end"],
    )
    if analysis_year_range["start"] is None:
        historical_death_records = with_death_date.iloc[0:0]
        historical_death_count = 0
    else:
        historical_death_records = (
            with_death_date[with_death_date["death_year"] < analysis_year_range["start"]]
            .sort_values(["death_year", "death_date", "person_id"])
            .head(12)
        )
        historical_death_count = int(
            (with_death_date["death_year"] < analysis_year_range["start"]).sum()
        )
    age_bucket_counts = (
        with_age.assign(
            age_bucket=with_age["age_at_death"].apply(_age_bucket_label),
        )["age_bucket"]
        .value_counts()
        .reindex(_age_bucket_labels(), fill_value=0)
    )
    age_gender_counts = _group_counts_by_gender(
        with_age.assign(age_bucket=with_age["age_at_death"].apply(_age_bucket_label)),
        "age_bucket",
        _age_bucket_labels(),
    )
    homyo_ingo_analysis = _homyo_ingo_analysis(
        memorial_members,
        start_year=analysis_year_range["start"],
        end_year=analysis_year_range["end"],
    )
    homyo_ingo_type_analysis = _homyo_ingo_type_analysis(
        memorial_members,
        start_year=analysis_year_range["start"],
        end_year=analysis_year_range["end"],
    )
    homyo_analysis = _homyo_character_analysis(memorial_members)
    top_households = sorted(
        (
            {
                "household_id": detail["summary"]["household_id"],
                "household_name": detail["summary"]["name"],
                "memorial_count": detail["summary"]["memorial_count"],
            }
            for detail in dataset["household_details"].values()
            if detail["summary"]["memorial_count"] > 0
        ),
        key=lambda item: (
            -item["memorial_count"],
            _sort_text(item["household_name"]),
            _int_sort(item["household_id"]),
        ),
    )[:12]
    household_concentration_analysis = _household_concentration_analysis(
        [
            {
                "household_id": detail["summary"]["household_id"],
                "household_name": detail["summary"]["name"],
                "memorial_count": detail["summary"]["memorial_count"],
            }
            for detail in dataset["household_details"].values()
        ]
    )

    return {
        "memorial_members": memorial_members,
        "with_death_date": with_death_date,
        "analysis_year_values": analysis_year_values,
        "analysis_year_range": analysis_year_range,
        "analysis_year_rule_label": _analysis_year_rule_label(analysis_year_range),
        "death_year_range": {
            "oldest": int(year_counts.index.min()) if not year_counts.empty else None,
            "latest": int(year_counts.index.max()) if not year_counts.empty else None,
        },
        "memorial_member_total": len(memorial_members),
        "with_death_date_count": int(len(with_death_date)),
        "with_age_count": int(len(with_age)),
        "unparsed_death_date_count": int(len(parse_failed_dates)),
        "as_of_date": active_as_of_date.isoformat(),
        "future_death_date_count": int(len(future_death_dates)),
        "partial_year": partial_year,
        "partial_year_count": partial_year_count,
        "analysis_record_count": int(len(analysis_with_death_date)),
        "calendar_analysis_count": int(len(calendar_death_dates)),
        "calendar_observation_start": calendar_observation_start.isoformat()
        if calendar_observation_start is not None
        else None,
        "calendar_observation_end": active_as_of_date.isoformat(),
        "calendar_observation_day_count": calendar_observation_day_count,
        "month_day_distribution": month_day_distribution,
        "death_decade_month_analysis": death_decade_month_analysis,
        "death_decade_age_analysis": death_decade_age_analysis,
        "average_age_trend_analysis": average_age_trend_analysis,
        "annual_age_sum_trend_analysis": annual_age_sum_trend_analysis,
        "month_day_bias_analysis": month_day_bias_analysis,
        "month_day_overlap_distribution": month_day_overlap_distribution,
        "interval_distribution": interval_distribution,
        "poisson_consistency": poisson_consistency,
        "interval_survival_analysis": interval_survival_analysis,
        "interval_qq_analysis": interval_qq_analysis,
        "year_count_diagnostics": year_count_diagnostics,
        "year_count_distribution": year_count_distribution,
        "year_month_heatmap_analysis": year_month_heatmap_analysis,
        "same_day_cluster_analysis": same_day_cluster_analysis,
        "household_concentration_analysis": household_concentration_analysis,
        "completeness_by_decade_analysis": completeness_by_decade_analysis,
        "month_day_details": _month_day_details(
            calendar_death_dates,
            month_day_distribution["grid_rows"],
        ),
        "death_year_details": _death_year_details(with_death_date, analysis_year_values),
        "historical_death_count": historical_death_count,
        "historical_death_records": _historical_death_records_payload(
            historical_death_records
        ),
        "homyo_ingo_analysis": homyo_ingo_analysis,
        "homyo_ingo_type_analysis": homyo_ingo_type_analysis,
        "homyo_analysis": homyo_analysis,
        "month_gender_counts": month_gender_counts,
        "month_gender_rates": month_gender_rates,
        "weekday_gender_counts": weekday_gender_counts,
        "weekday_gender_rates": weekday_gender_rates,
        "analysis_year_gender_counts": analysis_year_gender_counts,
        "age_gender_counts": age_gender_counts,
        "death_month_rows": _series_rows(month_counts),
        "death_year_rows": _series_rows(analysis_year_counts),
        "age_bucket_rows": _series_rows(age_bucket_counts),
        "top_households": top_households,
        "active_month_cohort_mode": month_cohort_mode,
        "active_age_cohort_mode": age_cohort_mode,
    }
