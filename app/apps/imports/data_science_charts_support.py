from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .data_science_shared import base_dir

__all__ = [
    "_graphics_runtime_dir",
    "_configure_graphics_runtime",
    "_matplotlib_font_name",
    "_configure_matplotlib",
]


@lru_cache(maxsize=1)
def _graphics_runtime_dir() -> Path:
    runtime_dir = base_dir() / "data" / "generated" / "matplotlib"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def _configure_graphics_runtime() -> Path:
    runtime_dir = _graphics_runtime_dir()
    os.environ.setdefault("MPLCONFIGDIR", str(runtime_dir))
    os.environ.setdefault("XDG_CACHE_HOME", str(runtime_dir / "cache"))
    (runtime_dir / "cache").mkdir(parents=True, exist_ok=True)
    return runtime_dir


@lru_cache(maxsize=1)
def _matplotlib_font_name() -> str:
    _configure_graphics_runtime()
    from matplotlib import font_manager

    available = {font.name for font in font_manager.fontManager.ttflist}
    for name in (
        "Hiragino Sans",
        "Hiragino Kaku Gothic ProN",
        "Yu Gothic",
        "Noto Sans CJK JP",
        "IPAexGothic",
        "IPAGothic",
    ):
        if name in available:
            return name
    return "DejaVu Sans"


def _configure_matplotlib() -> None:
    _configure_graphics_runtime()
    import matplotlib

    matplotlib.rcParams["font.family"] = _matplotlib_font_name()
    matplotlib.rcParams["font.sans-serif"] = [
        _matplotlib_font_name(),
        "Hiragino Sans",
        "Yu Gothic",
        "Noto Sans CJK JP",
        "IPAexGothic",
        "DejaVu Sans",
    ]
    matplotlib.rcParams["axes.unicode_minus"] = False
    matplotlib.rcParams["svg.fonttype"] = "none"


__all__ = [
    "_graphics_runtime_dir",
    "_configure_graphics_runtime",
    "_matplotlib_font_name",
    "_configure_matplotlib",
]
