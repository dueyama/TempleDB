from __future__ import annotations

from io import StringIO

from .data_science_charts_support import _configure_matplotlib
from .data_science_shared import GENDER_LABELS


def _place_horizontal_legend_above_plot(axis, *, column_count: int) -> None:
    axis.legend(
        frameon=False,
        fontsize=9,
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        borderaxespad=0.0,
        ncol=column_count,
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
    _configure_matplotlib()
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    first_series = next(iter(series_map.values()), None)
    labels = [str(index) for index in first_series.index] if first_series is not None else []
    positions = list(range(len(labels)))
    width = 0.72 / max(len(category_labels), 1)
    figure = Figure(figsize=figsize, tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    for offset_index, category_label in enumerate(category_labels):
        series = series_map.get(category_label)
        values = [float(value) for value in series.values] if series is not None else [0.0] * len(labels)
        offset = (offset_index - ((len(category_labels) - 1) / 2.0)) * width
        axis.bar(
            [position + offset for position in positions],
            values,
            width=width,
            color=colors.get(category_label, "#999999"),
            label=category_label,
        )

    axis.set_title(title, fontsize=15, pad=44)
    axis.set_ylabel(f"{ylabel} (%)", fontsize=11)
    axis.grid(axis="y", alpha=0.25, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.set_xticks(positions)
    axis.set_xticklabels(labels, rotation=tick_rotation, ha="right" if tick_rotation else "center")
    axis.tick_params(axis="x", labelsize=10)
    axis.tick_params(axis="y", labelsize=10)
    axis.set_ylim(0, 100)
    _place_horizontal_legend_above_plot(
        axis,
        column_count=min(len(category_labels), 3),
    )

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


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
    _configure_matplotlib()
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    first_series = next(iter(series_map.values()), None)
    labels = [str(index) for index in first_series.index] if first_series is not None else []
    figure = Figure(figsize=figsize, tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    bottoms = [0.0] * len(labels) if preserve_floats else [0] * len(labels)
    for gender in GENDER_LABELS:
        series = series_map.get(gender)
        if series is None:
            values = [0.0] * len(labels) if preserve_floats else [0] * len(labels)
        elif preserve_floats:
            values = [float(value) for value in series.values]
        else:
            values = [int(value) for value in series.values]
        axis.bar(
            labels,
            values,
            bottom=bottoms,
            color=colors.get(gender, "#999999"),
            width=0.75,
            label=gender,
        )
        bottoms = [base + value for base, value in zip(bottoms, values, strict=True)]

    axis.set_title(title, fontsize=15, pad=16)
    axis.set_ylabel(ylabel, fontsize=11)
    axis.grid(axis="y", alpha=0.25, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="x", rotation=tick_rotation, labelsize=x_tick_labelsize)
    axis.tick_params(axis="y", labelsize=10)
    if bottoms:
        max_total = max(bottoms)
        axis.set_ylim(0, max_total * (1.24 if annotate_totals else 1.16) if max_total > 0 else 1)
    if annotate_totals:
        max_total = max(bottoms) if bottoms else 0
        label_offset = max(max_total * 0.015, 0.2)
        for index, total in enumerate(bottoms):
            if total <= 0:
                continue
            axis.text(
                index,
                total + label_offset,
                str(total),
                ha="center",
                va="bottom",
                fontsize=annotation_fontsize,
                color="#5d4631",
                fontweight="bold",
            )
    axis.legend(frameon=False, fontsize=9, loc="upper right", ncol=len(GENDER_LABELS))

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


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
    _configure_matplotlib()
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    figure = Figure(figsize=figsize, tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    bottoms = [0.0] * len(labels)
    for stack_label in stack_labels:
        series = series_map.get(stack_label)
        values = [float(value) for value in series.values] if series is not None else [0.0] * len(labels)
        axis.bar(
            labels,
            values,
            bottom=bottoms,
            color=colors.get(stack_label, "#999999"),
            width=0.75,
            label=stack_label,
        )
        bottoms = [base + value for base, value in zip(bottoms, values, strict=True)]

    axis.set_title(title, fontsize=15, pad=44)
    axis.set_ylabel(f"{ylabel} (%)", fontsize=11)
    axis.grid(axis="y", alpha=0.25, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="x", rotation=tick_rotation, labelsize=10)
    axis.tick_params(axis="y", labelsize=10)
    axis.set_ylim(0, 100)
    _place_horizontal_legend_above_plot(
        axis,
        column_count=min(len(stack_labels), 4),
    )

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()
