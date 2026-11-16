from __future__ import annotations

from io import StringIO

from .data_science_charts_support import _configure_matplotlib

__all__ = [
    "_render_month_day_overlap_distribution_svg",
    "_render_lorenz_curve_svg",
    "_render_month_day_heatmap_svg",
    "_render_matrix_heatmap_svg",
    "_render_signed_heatmap_svg",
]


def _render_month_day_overlap_distribution_svg(
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
        observed_frequency_values = analysis.get("observed_frequency_values") or []
        expected_poisson_values = analysis.get("expected_poisson_values") or []
        stats = analysis.get("stats") or {}

        axis.bar(
            count_values,
            observed_frequency_values,
            width=0.82,
            color="#d8c2a6",
            edgecolor="#fff8ee",
            alpha=0.9,
            label="観測セル数",
        )
        if count_values and expected_poisson_values:
            axis.plot(
                count_values,
                expected_poisson_values,
                color="#7a3b1d",
                linewidth=2.2,
                marker="o",
                markersize=4.5,
                label=f"Poisson 期待 (λ={stats.get('lambda_per_day', 0):.3f})",
            )
            axis.legend(frameon=False, fontsize=9, loc="upper right")

        if count_values:
            axis.set_xticks(count_values)
            lower = min(count_values) - 0.8
            upper = max(count_values) + 0.8
            if lower == upper:
                lower -= 0.5
                upper += 0.5
            axis.set_xlim(lower, upper)

        max_bar = max(observed_frequency_values) if observed_frequency_values else 0
        max_fit = max(expected_poisson_values) if expected_poisson_values else 0
        axis.set_ylim(0, max(1, max(max_bar, max_fit) * 1.16))

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


def _render_lorenz_curve_svg(analysis: dict, *, title: str) -> str:
    _configure_matplotlib()
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    figure = Figure(figsize=(6.2, 6.2), tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    axis.set_title(title, fontsize=15, pad=16)
    axis.set_ylabel("累積過去帳比率", fontsize=11)
    axis.set_xlabel("累積 household 比率", fontsize=11)
    axis.grid(axis="both", alpha=0.25, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="x", labelsize=10)
    axis.tick_params(axis="y", labelsize=10)

    if not analysis.get("available"):
        axis.text(0.5, 0.5, "データなし", ha="center", va="center", fontsize=14)
    else:
        x_values = analysis["household_share_points"]
        y_values = analysis["record_share_points"]
        axis.plot([0, 1], [0, 1], color="#9a9388", linewidth=1.6, linestyle=(0, (4, 2)), label="均等線")
        axis.plot(x_values, y_values, color="#8f5f2c", linewidth=2.2, label=f"Lorenz (Gini {analysis['gini']:.3f})")
        axis.set_xlim(0, 1)
        axis.set_ylim(0, 1)
        axis.set_aspect("equal", adjustable="box")
        axis.legend(frameon=False, fontsize=9, loc="upper left")

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


def _render_month_day_heatmap_svg(matrix, *, title: str) -> str:
    import numpy as np

    _configure_matplotlib()
    import matplotlib
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    figure = Figure(figsize=(12.0, 5.4), tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    axis.set_title(title, fontsize=15, pad=16)
    axis.set_xlabel("日", fontsize=11)
    axis.set_ylabel("月", fontsize=11)
    axis.set_xticks(list(range(0, 31, 2)))
    axis.set_xticklabels([str(day) for day in range(1, 32, 2)], fontsize=9)
    axis.set_yticks(list(range(12)))
    axis.set_yticklabels([f"{month}月" for month in range(1, 13)], fontsize=10)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_visible(False)
    axis.spines["bottom"].set_visible(False)
    if np.isfinite(matrix).any():
        masked = np.ma.masked_invalid(matrix)
        cmap = matplotlib.colormaps["YlOrRd"].copy()
        cmap.set_bad(color="#eee7dc")
        observed_max = float(np.nanmax(matrix))
        vmax = observed_max if observed_max > 0 else 1.0
        image = axis.imshow(
            masked,
            aspect="auto",
            cmap=cmap,
            interpolation="nearest",
            vmin=0,
            vmax=vmax,
        )
        colorbar = figure.colorbar(image, ax=axis, shrink=0.86, pad=0.02)
        colorbar.ax.set_ylabel("件数", rotation=90, fontsize=10)
        colorbar.ax.tick_params(labelsize=9)
    else:
        axis.text(15, 5.5, "データなし", ha="center", va="center", fontsize=14)

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


def _render_matrix_heatmap_svg(
    matrix,
    *,
    row_labels: list[str],
    column_labels: list[str],
    title: str,
    xlabel: str,
    ylabel: str,
    colorbar_label: str = "件数",
    vmin: float | None = None,
    vmax: float | None = None,
) -> str:
    import numpy as np

    _configure_matplotlib()
    import matplotlib
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    figure = Figure(
        figsize=(max(8.0, len(column_labels) * 0.62), max(4.8, len(row_labels) * 0.42)),
        tight_layout=True,
    )
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    axis.set_title(title, fontsize=15, pad=16)
    axis.set_xlabel(xlabel, fontsize=11)
    axis.set_ylabel(ylabel, fontsize=11)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_visible(False)
    axis.spines["bottom"].set_visible(False)

    if np.size(matrix) and np.isfinite(matrix).any():
        masked = np.ma.masked_invalid(matrix)
        cmap = matplotlib.colormaps["YlOrRd"].copy()
        cmap.set_bad(color="#eee7dc")
        resolved_vmin = vmin
        resolved_vmax = vmax
        if resolved_vmin is not None and resolved_vmax is None:
            observed_max = float(np.nanmax(matrix))
            resolved_vmax = (
                observed_max if observed_max > resolved_vmin else resolved_vmin + 1.0
            )
        image = axis.imshow(
            masked,
            aspect="auto",
            cmap=cmap,
            interpolation="nearest",
            vmin=resolved_vmin,
            vmax=resolved_vmax,
        )
        axis.set_xticks(list(range(len(column_labels))))
        axis.set_xticklabels(column_labels, rotation=35, ha="right", fontsize=9)
        axis.set_yticks(list(range(len(row_labels))))
        axis.set_yticklabels(row_labels, fontsize=9)
        colorbar = figure.colorbar(image, ax=axis, shrink=0.86, pad=0.02)
        colorbar.ax.set_ylabel(colorbar_label, rotation=90, fontsize=10)
        colorbar.ax.tick_params(labelsize=9)
    else:
        axis.text(0.5, 0.5, "データなし", ha="center", va="center", fontsize=14)
        axis.set_xticks([])
        axis.set_yticks([])

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


def _render_signed_heatmap_svg(
    matrix,
    *,
    row_labels: list[str],
    column_labels: list[str],
    title: str,
    xlabel: str,
    ylabel: str,
    colorbar_label: str,
) -> str:
    import numpy as np

    _configure_matplotlib()
    import matplotlib
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    figure = Figure(figsize=(12.0, 5.4), tight_layout=True)
    FigureCanvasSVG(figure)
    axis = figure.subplots()
    axis.set_title(title, fontsize=15, pad=16)
    axis.set_xlabel(xlabel, fontsize=11)
    axis.set_ylabel(ylabel, fontsize=11)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_visible(False)
    axis.spines["bottom"].set_visible(False)

    if np.size(matrix) and np.isfinite(matrix).any():
        masked = np.ma.masked_invalid(matrix)
        vmax = max(float(np.nanmax(np.abs(matrix))), 1.0)
        norm = matplotlib.colors.TwoSlopeNorm(vmin=-vmax, vcenter=0.0, vmax=vmax)
        cmap = matplotlib.colormaps["RdBu_r"].copy()
        cmap.set_bad(color="#eee7dc")
        image = axis.imshow(masked, aspect="auto", cmap=cmap, norm=norm, interpolation="nearest")
        axis.set_xticks(list(range(0, len(column_labels), 2)))
        axis.set_xticklabels(column_labels[::2], fontsize=9)
        axis.set_yticks(list(range(len(row_labels))))
        axis.set_yticklabels(row_labels, fontsize=9)
        colorbar = figure.colorbar(image, ax=axis, shrink=0.86, pad=0.02)
        colorbar.ax.set_ylabel(colorbar_label, rotation=90, fontsize=10)
        colorbar.ax.tick_params(labelsize=9)
    else:
        axis.text(0.5, 0.5, "データなし", ha="center", va="center", fontsize=14)
        axis.set_xticks([])
        axis.set_yticks([])

    buffer = StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


__all__ = [
    "_render_month_day_overlap_distribution_svg",
    "_render_lorenz_curve_svg",
    "_render_month_day_heatmap_svg",
    "_render_matrix_heatmap_svg",
    "_render_signed_heatmap_svg",
]
