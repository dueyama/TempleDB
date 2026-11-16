from __future__ import annotations

import sys

if len(sys.argv) < 2 or sys.argv[1] != "migrate":
    raise RuntimeError(
        "config.settings_product_sqlite_initialization is reserved for the dedicated "
        "product SQLite migrate subprocess."
    )

from .settings import *  # noqa: E402,F403

if not TEMPLEDB_PRODUCT_SQLITE_MODE:  # noqa: F405
    raise RuntimeError("Product SQLite initialization requires TEMPLEDB_DATABASE_ENGINE=sqlite.")
