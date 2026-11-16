from __future__ import annotations

from io import StringIO

from .data_science_charts_support import _configure_matplotlib
from .data_science_shared import GENDER_LABELS


def _render_bar_chart_svg(
    series,
    *,
    title: str,
    ylabel: str,
    color: str,
    tick_rotation: int,
    figsize: tuple[float, float] = (10.6, 4.8),
) -> str:
    _configure_matplotlib()
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    labels = [str(index) for index in series.index]
    values = [int(value) for value in series.values]
    figure = Figure(figsize=figsize, tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    axis.bar(labels, values, color=color, width=0.75)
    axis.set_title(title, fontsize=15, pad=16)
    axis.set_ylabel(ylabel, fontsize=11)
    axis.grid(axis="y", alpha=0.25, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="x", rotation=tick_rotation, labelsize=10)
    axis.tick_params(axis="y", labelsize=10)
    if values:
        axis.set_ylim(0, max(values) * 1.15 if max(values) > 0 else 1)
    for patch, value in zip(axis.patches, values, strict=True):
        axis.text(
            patch.get_x() + patch.get_width() / 2,
            patch.get_height(),
            str(value),
            ha="center",
            va="bottom",
            fontsize=9,
            color="#5d4631",
        )

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


def _render_rate_bar_chart_svg(
    series,
    *,
    title: str,
    ylabel: str,
    color: str,
    tick_rotation: int,
    figsize: tuple[float, float] = (10.6, 4.8),
) -> str:
    _configure_matplotlib()
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    labels = [str(index) for index in series.index]
    values = [float(value) for value in series.values]
    figure = Figure(figsize=figsize, tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    axis.bar(labels, values, color=color, width=0.75)
    axis.set_title(title, fontsize=15, pad=16)
    axis.set_ylabel(f"{ylabel} (%)", fontsize=11)
    axis.grid(axis="y", alpha=0.25, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="x", rotation=tick_rotation, labelsize=10)
    axis.tick_params(axis="y", labelsize=10)
    axis.set_ylim(0, 100)
    for patch, value in zip(axis.patches, values, strict=True):
        axis.text(
            patch.get_x() + patch.get_width() / 2,
            patch.get_height(),
            f"{value:.1f}%",
            ha="center",
            va="bottom",
            fontsize=9,
            color="#5d4631",
        )

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


def _render_grouped_bar_chart_svg(
    series_map,
    *,
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
    width = 0.24
    figure = Figure(figsize=figsize, tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    for offset_index, gender in enumerate(GENDER_LABELS):
        series = series_map.get(gender)
        values = [int(value) for value in series.values] if series is not None else [0] * len(labels)
        offset = (offset_index - 1) * width
        axis.bar(
            [position + offset for position in positions],
            values,
            width=width,
            color=colors.get(gender, "#999999"),
            label=gender,
        )

    axis.set_title(title, fontsize=15, pad=16)
    axis.set_ylabel(ylabel, fontsize=11)
    axis.grid(axis="y", alpha=0.25, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.set_xticks(positions)
    axis.set_xticklabels(labels, rotation=tick_rotation, ha="right" if tick_rotation else "center")
    axis.tick_params(axis="x", labelsize=10)
    axis.tick_params(axis="y", labelsize=10)
    axis.legend(frameon=False, fontsize=9, loc="upper right", ncol=len(GENDER_LABELS))

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()
