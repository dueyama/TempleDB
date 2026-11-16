from __future__ import annotations

from . import (
    data_science_chart_bars,
    data_science_chart_lines,
    data_science_chart_stacks,
)

__all__ = [
    "_render_bar_chart_svg",
    "_render_rate_bar_chart_svg",
    "_render_grouped_rate_bar_chart_svg",
    "_render_stacked_bar_chart_svg",
    "_render_stacked_percentage_bar_chart_svg",
    "_render_grouped_bar_chart_svg",
    "_render_multi_line_chart_svg",
    "_render_age_histogram_svg",
]


def _render_bar_chart_svg(
    series,
    *,
    title: str,
    ylabel: str,
    color: str,
    tick_rotation: int,
    figsize: tuple[float, float] = (10.6, 4.8),
) -> str:
    return data_science_chart_bars._render_bar_chart_svg(
        series,
        title=title,
        ylabel=ylabel,
        color=color,
        tick_rotation=tick_rotation,
        figsize=figsize,
    )


def _render_rate_bar_chart_svg(
    series,
    *,
    title: str,
    ylabel: str,
    color: str,
    tick_rotation: int,
    figsize: tuple[float, float] = (10.6, 4.8),
) -> str:
    return data_science_chart_bars._render_rate_bar_chart_svg(
        series,
        title=title,
        ylabel=ylabel,
        color=color,
        tick_rotation=tick_rotation,
        figsize=figsize,
    )


def _render_grouped_rate_bar_chart_svg(
    series_map,
    *,
    category_labels: list[str],
    title: str,
    ylabel: str,
    colors: dict[str, str],
    tick_rotation: int,
    figsize: tuple[float, float] = (10.6, 4.8),
) -> str:
    return data_science_chart_stacks._render_grouped_rate_bar_chart_svg(
        series_map,
        category_labels=category_labels,
        title=title,
        ylabel=ylabel,
        colors=colors,
        tick_rotation=tick_rotation,
        figsize=figsize,
    )


def _render_stacked_bar_chart_svg(
    series_map,
    *,
    title: str,
    ylabel: str,
    colors: dict[str, str],
    tick_rotation: int,
    preserve_floats: bool = False,
    annotate_totals: bool = False,
    x_tick_labelsize: float = 10,
    annotation_fontsize: float = 9,
    figsize: tuple[float, float] = (10.6, 4.8),
) -> str:
    return data_science_chart_stacks._render_stacked_bar_chart_svg(
        series_map,
        title=title,
        ylabel=ylabel,
        colors=colors,
        tick_rotation=tick_rotation,
        preserve_floats=preserve_floats,
        annotate_totals=annotate_totals,
        x_tick_labelsize=x_tick_labelsize,
        annotation_fontsize=annotation_fontsize,
        figsize=figsize,
    )


def _render_stacked_percentage_bar_chart_svg(
    series_map,
    *,
    labels: list[str],
    stack_labels: list[str],
    title: str,
    ylabel: str,
    colors: dict[str, str],
    tick_rotation: int,
    figsize: tuple[float, float] = (10.6, 4.8),
) -> str:
    return data_science_chart_stacks._render_stacked_percentage_bar_chart_svg(
        series_map,
        labels=labels,
        stack_labels=stack_labels,
        title=title,
        ylabel=ylabel,
        colors=colors,
        tick_rotation=tick_rotation,
        figsize=figsize,
    )


def _render_grouped_bar_chart_svg(
    series_map,
    *,
    title: str,
    ylabel: str,
    colors: dict[str, str],
    tick_rotation: int,
    figsize: tuple[float, float] = (10.6, 4.8),
) -> str:
    return data_science_chart_bars._render_grouped_bar_chart_svg(
        series_map,
        title=title,
        ylabel=ylabel,
        colors=colors,
        tick_rotation=tick_rotation,
        figsize=figsize,
    )


def _render_multi_line_chart_svg(
    series_map,
    *,
    title: str,
    ylabel: str,
    colors: dict[str, str],
    tick_rotation: int,
    overlay_series_map=None,
    x_tick_step: int = 5,
    x_tick_labelsize: float = 8,
    figsize: tuple[float, float] = (10.8, 4.8),
) -> str:
    return data_science_chart_lines._render_multi_line_chart_svg(
        series_map,
        title=title,
        ylabel=ylabel,
        colors=colors,
        tick_rotation=tick_rotation,
        overlay_series_map=overlay_series_map,
        x_tick_step=x_tick_step,
        x_tick_labelsize=x_tick_labelsize,
        figsize=figsize,
    )


def _render_age_histogram_svg(
    ages: list[int],
    *,
    title: str,
    ylabel: str,
) -> str:
    return data_science_chart_lines._render_age_histogram_svg(
        ages,
        title=title,
        ylabel=ylabel,
    )
