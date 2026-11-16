from __future__ import annotations

# Compatibility facade: keep the outward import path stable while owner modules
# hold the implementation. Star-import order defines duplicate-name precedence.
# isort: off
from .data_science_shared import *  # noqa: F401,F403
from .data_science_context import *  # noqa: F401,F403
from .data_science_analysis import *  # noqa: F401,F403
from .data_science_charts import *  # noqa: F401,F403
# isort: on
