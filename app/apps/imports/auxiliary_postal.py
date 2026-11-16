from __future__ import annotations

from . import (
    auxiliary_postal_analysis,
    auxiliary_postal_import,
    auxiliary_postal_labels,
    auxiliary_postal_review,
    auxiliary_postal_sources,
)
from .models import HOUSEHOLD_DELIVERY_POSTAL as HOUSEHOLD_DELIVERY_POSTAL
from .source_runtime import (
    latest_export_snapshot as latest_export_snapshot,
)
from .source_runtime import (
    latest_succeeded_import_batch as latest_succeeded_import_batch,
)

list_auxiliary_postal_csv_candidates = auxiliary_postal_sources.list_auxiliary_postal_csv_candidates
latest_auxiliary_postal_csv_path = auxiliary_postal_sources.latest_auxiliary_postal_csv_path
import_postal_assignments = auxiliary_postal_import.import_postal_assignments
analyze_postal_rows = auxiliary_postal_analysis.analyze_postal_rows
build_postal_compare_context = auxiliary_postal_review.build_postal_compare_context
_postal_marker_text = auxiliary_postal_labels._postal_marker_text
build_postal_label_context = auxiliary_postal_labels.build_postal_label_context
build_district_officer_postal_label_context = (
    auxiliary_postal_labels.build_district_officer_postal_label_context
)
search_households_for_postal_review = auxiliary_postal_review.search_households_for_postal_review
