from __future__ import annotations

from apps.imports.auxiliary_generated_ids import (
    _next_generated_household_id as _next_generated_household_id,
)
from apps.imports.auxiliary_generated_ids import (
    _next_generated_household_row_number as _next_generated_household_row_number,
)
from apps.office.services.auxiliary_hand_delivery_households import (
    _create_household_from_hand_delivery_entry as _create_household_from_hand_delivery_entry,
)
from apps.office.services.auxiliary_hand_delivery_households import (
    _replace_household_head_from_hand_delivery_entry as _replace_household_head_from_hand_delivery_entry,
)
from apps.office.services.auxiliary_postal_households import (
    _create_household_from_postal_entry as _create_household_from_postal_entry,
)
from apps.office.services.auxiliary_postal_households import (
    _ensure_postal_recipient_current_person as _ensure_postal_recipient_current_person,
)
from apps.office.services.auxiliary_postal_households import (
    _replace_household_head_from_postal_entry as _replace_household_head_from_postal_entry,
)
from apps.office.services.district_ops import (
    _assign_district_officer_to_household as _assign_district_officer_to_household,
)
from apps.office.services.district_ops import (
    _district_officer_choices as _district_officer_choices,
)
from apps.office.services.district_ops import (
    _ensure_district_from_hand_delivery_entry as _ensure_district_from_hand_delivery_entry,
)
from apps.office.services.district_ops import (
    _refresh_district_officer_name_snapshots as _refresh_district_officer_name_snapshots,
)
from apps.office.views.settings_auxiliary_shared import (
    _rollbackable_created_auxiliary_household as _rollbackable_created_auxiliary_household,
)
from apps.office.views.settings_district_admin import districts as districts
from apps.office.views.settings_hand_delivery_head_actions import (
    replace_hand_delivery_household_head as replace_hand_delivery_household_head,
)
from apps.office.views.settings_hand_delivery_household_actions import (
    create_hand_delivery_review_household as create_hand_delivery_review_household,
)
from apps.office.views.settings_hand_delivery_household_actions import (
    rollback_created_hand_delivery_review_household as rollback_created_hand_delivery_review_household,
)
from apps.office.views.settings_hand_delivery_review_views import (
    _find_hand_delivery_review_entry as _find_hand_delivery_review_entry,
)
from apps.office.views.settings_hand_delivery_review_views import (
    _record_hand_delivery_review_resolution as _record_hand_delivery_review_resolution,
)
from apps.office.views.settings_hand_delivery_review_views import (
    hand_delivery_review as hand_delivery_review,
)
from apps.office.views.settings_hand_delivery_review_views import (
    import_hand_delivery_districts as import_hand_delivery_districts,
)

# These renamed exports preserve the historic apps.imports import paths.
from apps.office.views.settings_home_admin import (
    settings_home as _legacy_settings_home,  # noqa: F401
)
from apps.office.views.settings_household_delivery import household_districts as household_districts
from apps.office.views.settings_membership_fees import (
    _build_annual_membership_fee_context as _build_annual_membership_fee_context,
)
from apps.office.views.settings_membership_fees import (
    annual_membership_fees as annual_membership_fees,
)
from apps.office.views.settings_postal_head_actions import (
    replace_postal_household_head as replace_postal_household_head,
)
from apps.office.views.settings_postal_household_actions import (
    create_postal_review_household as create_postal_review_household,
)
from apps.office.views.settings_postal_household_actions import (
    rollback_created_postal_review_household as rollback_created_postal_review_household,
)
from apps.office.views.settings_postal_override_actions import (
    assign_postal_override as assign_postal_override,
)
from apps.office.views.settings_postal_reports import postal_compare as postal_compare
from apps.office.views.settings_postal_review_views import (
    _find_postal_review_entry as _find_postal_review_entry,
)
from apps.office.views.settings_postal_review_views import (
    _record_postal_review_resolution as _record_postal_review_resolution,
)
from apps.office.views.settings_postal_review_views import (
    import_postal_assignments as import_postal_assignments,
)
from apps.office.views.settings_postal_review_views import (
    postal_review as postal_review,
)
from apps.office.views.settings_user_management import (
    user_management as _legacy_user_management,  # noqa: F401
)
