from __future__ import annotations

import math
from io import StringIO

from .data_science_charts_support import _configure_matplotlib


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
    _configure_matplotlib()
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    first_series = next(iter(series_map.values()), None)
    labels = [str(index) for index in first_series.index] if first_series is not None else []
    positions = list(range(len(labels)))
    figure = Figure(figsize=figsize, tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    axis.set_title(title, fontsize=15, pad=16)
    axis.set_ylabel(ylabel, fontsize=11)
    axis.set_xlabel("命日年", fontsize=11)
    axis.grid(axis="y", alpha=0.25, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)

    finite_values: list[float] = []
    for label, series in series_map.items():
        values = [float(value) if value == value else math.nan for value in series.values]
        finite_values.extend([value for value in values if not math.isnan(value)])
        axis.plot(
            positions,
            values,
            color=colors.get(label, "#999999"),
            linewidth=2.2,
            label=label,
        )
    if overlay_series_map:
        for label, series in overlay_series_map.items():
            values = [float(value) if value == value else math.nan for value in series.values]
            finite_values.extend([value for value in values if not math.isnan(value)])
            axis.plot(
                positions,
                values,
                color=colors.get(label, "#999999"),
                linewidth=1.5,
                linestyle=(0, (4, 2)),
                alpha=0.72,
            )

    if labels:
        selected_positions = sorted(
            {
                index
                for index in positions
                if x_tick_step <= 1 or index % x_tick_step == 0 or index == len(labels) - 1
            }
        )
        axis.set_xticks(selected_positions)
        axis.set_xticklabels(
            [labels[index] for index in selected_positions],
            rotation=tick_rotation,
            ha="right" if tick_rotation else "center",
            fontsize=x_tick_labelsize,
        )
        if len(labels) == 1:
            axis.set_xlim(-0.5, 0.5)
        else:
            axis.set_xlim(0, len(labels) - 1)
    if finite_values:
        minimum = min(finite_values)
        maximum = max(finite_values)
        padding = max((maximum - minimum) * 0.12, 1.2)
        axis.set_ylim(max(0, minimum - padding), maximum + padding)
    else:
        axis.text(0.5, 0.5, "データなし", ha="center", va="center", fontsize=14)

    axis.tick_params(axis="y", labelsize=10)
    axis.legend(frameon=False, fontsize=9, loc="upper right", ncol=min(len(series_map), 3))

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


def _render_age_histogram_svg(
    ages: list[int],
    *,
    title: str,
    ylabel: str,
) -> str:
    _configure_matplotlib()
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    figure = Figure(figsize=(12.0, 5.4), tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    bins = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110]
    axis.hist(ages, bins=bins, color="#b17d1b", edgecolor="#fff8ee", rwidth=0.92)
    axis.set_title(title, fontsize=15, pad=16)
    axis.set_ylabel(ylabel, fontsize=11)
    axis.set_xlabel("享年", fontsize=11)
    axis.grid(axis="y", alpha=0.25, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="y", labelsize=10)
    axis.set_xticks([5, 15, 25, 35, 45, 55, 65, 75, 85, 95, 105])
    axis.set_xticklabels(
        ["10歳未満", "10代", "20代", "30代", "40代", "50代", "60代", "70代", "80代", "90代", "100歳以上"],
        rotation=35,
        ha="right",
        fontsize=10,
    )

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()
