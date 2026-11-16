from __future__ import annotations

import math
from io import StringIO

from .data_science_charts_support import _configure_matplotlib

__all__ = [
    "_render_interval_histogram_svg",
    "_render_interval_survival_svg",
    "_render_interval_qq_svg",
    "_render_year_count_diagnostics_svg",
    "_render_year_count_distribution_svg",
]


def _render_interval_histogram_svg(
    intervals: list[int],
    *,
    title: str,
    xlabel: str,
    ylabel: str,
    color: str,
    bin_width_days: int = 10,
    max_interval_days: int | None = None,
) -> str:
    if bin_width_days <= 0:
        raise ValueError("bin_width_days must be greater than zero")
    if max_interval_days is not None and max_interval_days < 0:
        raise ValueError("max_interval_days must be zero or greater")

    _configure_matplotlib()
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    figure = Figure(figsize=(10.8, 4.8), tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    axis.set_title(title, fontsize=15, pad=16)
    axis.set_ylabel(ylabel, fontsize=11)
    axis.set_xlabel(xlabel, fontsize=11)
    axis.grid(axis="y", alpha=0.25, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="x", labelsize=10)
    axis.tick_params(axis="y", labelsize=10)

    if not intervals:
        axis.text(0.5, 0.5, "データなし", ha="center", va="center", fontsize=14)
    else:
        display_intervals = intervals
        overflow_value = None
        if max_interval_days is not None and max(intervals) > max_interval_days:
            overflow_value = max_interval_days + 1
            display_intervals = [
                value if value <= max_interval_days else overflow_value
                for value in intervals
            ]

        max_interval = max(display_intervals)
        if bin_width_days == 1:
            upper = max_interval
            bins = [value - 0.5 for value in range(0, upper + 2)]
        else:
            upper = max(
                60,
                int(math.ceil(max_interval / float(bin_width_days)) * bin_width_days),
            )
            bins = list(range(0, upper + bin_width_days, bin_width_days))
        counts, edges, _ = axis.hist(
            display_intervals,
            bins=bins,
            color=color,
            edgecolor="#fff8ee",
            alpha=0.85,
        )
        mean_interval = sum(intervals) / len(intervals)
        if mean_interval > 0 and len(edges) > 1:
            curve_x = list(range(0, upper + 1))
            bin_width = edges[1] - edges[0]
            scale = len(intervals) * bin_width
            curve_y = [
                scale * (1.0 / mean_interval) * math.exp(-value / mean_interval)
                for value in curve_x
            ]
            axis.plot(
                curve_x,
                curve_y,
                color="#2e5b3b",
                linewidth=2.2,
                label=f"指数近似 (平均 {mean_interval:.1f}日)",
            )
            axis.legend(frameon=False, fontsize=9, loc="upper right")

        if bin_width_days == 1:
            if upper <= 20:
                tick_step = 1
            elif upper <= 60:
                tick_step = 5
            elif upper <= 180:
                tick_step = 10
            else:
                tick_step = max(10, int(math.ceil(upper / 180.0) * 10))
            tick_limit = max_interval_days if overflow_value is not None else upper
            tick_values = list(range(0, tick_limit + 1, tick_step))
            tick_labels = [str(value) for value in tick_values]
            if overflow_value is not None:
                tick_values.append(overflow_value)
                tick_labels.append(f"{overflow_value}日以上")
            axis.set_xticks(tick_values)
            axis.set_xticklabels(tick_labels)
            axis.set_xlim(-0.5, upper + 0.5)
        else:
            axis.set_xlim(0, upper)
        axis.set_ylim(0, max(counts) * 1.12 if len(counts) else 1)

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


def _render_interval_survival_svg(
    analysis: dict,
    *,
    title: str,
    xlabel: str,
    ylabel: str,
    color: str,
) -> str:
    _configure_matplotlib()
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    figure = Figure(figsize=(10.8, 4.8), tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    axis.set_title(title, fontsize=15, pad=16)
    axis.set_ylabel(ylabel, fontsize=11)
    axis.set_xlabel(xlabel, fontsize=11)
    axis.grid(axis="both", alpha=0.25, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="x", labelsize=10)
    axis.tick_params(axis="y", labelsize=10)

    if not analysis.get("available"):
        axis.text(0.5, 0.5, "データなし", ha="center", va="center", fontsize=14)
    else:
        x_values = analysis["x_values"]
        empirical = analysis["empirical_survival"]
        theoretical = analysis["theoretical_survival"]
        count = max(int(analysis.get("count") or 0), 1)

        axis.step(x_values, empirical, where="post", color=color, linewidth=2.2, label="実測 CCDF")
        if theoretical:
            axis.plot(
                x_values,
                theoretical,
                color="#2e5b3b",
                linewidth=1.8,
                linestyle=(0, (4, 2)),
                label=f"指数近似 (平均 {analysis.get('mean_days', 0):.1f}日)",
            )
        axis.set_yscale("log")
        axis.set_ylim(max(1.0 / count, 1e-3) * 0.8, 1.05)
        max_x = max(x_values) if x_values else 0
        axis.set_xlim(0, max(1, max_x))
        axis.legend(frameon=False, fontsize=9, loc="upper right")

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


def _render_interval_qq_svg(
    analysis: dict,
    *,
    title: str,
    xlabel: str,
    ylabel: str,
    color: str,
) -> str:
    _configure_matplotlib()
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    figure = Figure(figsize=(7.4, 7.0), tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    axis.set_title(title, fontsize=15, pad=16)
    axis.set_ylabel(ylabel, fontsize=11)
    axis.set_xlabel(xlabel, fontsize=11)
    axis.grid(axis="both", alpha=0.25, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="x", labelsize=10)
    axis.tick_params(axis="y", labelsize=10)

    observed = analysis.get("observed_quantiles") or []
    theoretical = analysis.get("theoretical_quantiles") or []
    if not observed or not theoretical:
        axis.text(0.5, 0.5, "データなし", ha="center", va="center", fontsize=14)
    else:
        axis.scatter(theoretical, observed, color=color, s=26, alpha=0.85)
        max_value = max(max(observed), max(theoretical), 1)
        axis.plot([0, max_value], [0, max_value], color="#7a7a7a", linewidth=1.6, linestyle=(0, (4, 2)))
        axis.set_xlim(0, max_value * 1.05)
        axis.set_ylim(0, max_value * 1.05)
        axis.set_aspect("equal", adjustable="box")

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


def _render_year_count_diagnostics_svg(
    analysis: dict,
    *,
    title: str,
    ylabel: str,
) -> str:
    _configure_matplotlib()
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    figure = Figure(figsize=(12.0, 5.2), tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    axis.set_title(title, fontsize=15, pad=16)
    axis.set_ylabel(ylabel, fontsize=11)
    axis.set_xlabel("命日年", fontsize=11)
    axis.grid(axis="y", alpha=0.25, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)

    observed_series = analysis.get("observed_series")
    trend_series = analysis.get("trend_series")
    labels = analysis.get("row_labels") or []
    if observed_series is None or len(labels) == 0:
        axis.text(0.5, 0.5, "データなし", ha="center", va="center", fontsize=14)
    else:
        positions = list(range(len(labels)))
        observed_values = [float(value) for value in observed_series.values]
        trend_values = [float(value) for value in trend_series.values]
        axis.bar(positions, observed_values, color="#d8c2a6", width=0.74, label="観測件数")
        axis.plot(positions, trend_values, color="#7a3b1d", linewidth=2.2, label="中心5年 moving average")
        selected_positions = sorted(
            {
                index
                for index in positions
                if index % 5 == 0 or index == len(labels) - 1
            }
        )
        axis.set_xticks(selected_positions)
        axis.set_xticklabels([labels[index] for index in selected_positions], rotation=45, ha="right")
        axis.tick_params(axis="x", labelsize=8)
        axis.tick_params(axis="y", labelsize=10)
        axis.set_xlim(-0.6, len(labels) - 0.4)
        max_value = max(max(observed_values), max(trend_values)) if observed_values and trend_values else 0
        axis.set_ylim(0, max(1, max_value * 1.18))
        axis.legend(frameon=False, fontsize=9, loc="upper right")

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


def _render_year_count_distribution_svg(
    analysis: dict,
    *,
    title: str,
    xlabel: str,
    ylabel: str,
) -> str:
    _configure_matplotlib()
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    figure = Figure(figsize=(10.8, 4.8), tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    axis.set_title(title, fontsize=15, pad=16)
    axis.set_ylabel(ylabel, fontsize=11)
    axis.set_xlabel(xlabel, fontsize=11)
    axis.grid(axis="y", alpha=0.25, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="x", labelsize=10)
    axis.tick_params(axis="y", labelsize=10)

    if not analysis.get("available"):
        axis.text(0.5, 0.5, "データなし", ha="center", va="center", fontsize=14)
    else:
        count_values = analysis.get("count_values") or []
        frequency_values = analysis.get("frequency_values") or []
        fit_x_values = analysis.get("fit_x_values") or []
        fit_y_values = analysis.get("fit_y_values") or []
        poisson_count_values = analysis.get("poisson_count_values") or []
        poisson_frequency_values = analysis.get("poisson_frequency_values") or []
        stats = analysis.get("stats") or {}

        axis.bar(
            count_values,
            frequency_values,
            width=0.82,
            color="#d8c2a6",
            edgecolor="#fff8ee",
            alpha=0.9,
            label="年次件数の頻度",
        )
        if fit_x_values and fit_y_values:
            axis.plot(
                fit_x_values,
                fit_y_values,
                color="#7a3b1d",
                linewidth=2.2,
                label=f"正規フィット (μ={stats.get('mean_count', 0):.2f}, σ={stats.get('std_count', 0):.2f})",
            )
        if poisson_count_values and poisson_frequency_values:
            axis.plot(
                poisson_count_values,
                poisson_frequency_values,
                color="#355c7d",
                linewidth=2.0,
                marker="o",
                markersize=4.2,
                label=f"Poisson フィット (λ={stats.get('poisson_lambda', 0):.2f})",
            )
        if (fit_x_values and fit_y_values) or (poisson_count_values and poisson_frequency_values):
            axis.legend(frameon=False, fontsize=9, loc="upper right")

        x_values = []
        if count_values:
            x_values.extend(count_values)
        if poisson_count_values:
            x_values.extend(poisson_count_values)
        if x_values:
            span = max(x_values) - min(x_values)
            tick_step = max(1, int(math.ceil(span / 10))) if span > 10 else 1
            tick_values = list(range(min(x_values), max(x_values) + 1, tick_step))
            if tick_values[-1] != max(x_values):
                tick_values.append(max(x_values))
            axis.set_xticks(tick_values)
            lower = min(x_values) - 0.8
            upper = max(x_values) + 0.8
            if lower == upper:
                lower -= 0.5
                upper += 0.5
            axis.set_xlim(lower, upper)

        max_bar = max(frequency_values) if frequency_values else 0
        max_fit = max(fit_y_values) if fit_y_values else 0
        max_poisson = max(poisson_frequency_values) if poisson_frequency_values else 0
        axis.set_ylim(0, max(1, max(max_bar, max_fit, max_poisson) * 1.16))

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


__all__ = [
    "_render_interval_histogram_svg",
    "_render_interval_survival_svg",
    "_render_interval_qq_svg",
    "_render_year_count_diagnostics_svg",
    "_render_year_count_distribution_svg",
]
