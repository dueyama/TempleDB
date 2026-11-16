from django.contrib.auth.decorators import login_required
from django.urls import path

from .views.accounting import accounting, nokotsudan_accounting
from .views.home import complete_service_from_home, home
from .views.household_browser_actions import (
    bulk_update_people_gender,
    clear_household_address_line2,
    delete_person_from_same_name_candidates,
    toggle_person_memorial_notice_opt_out,
    update_household_delivery_assignment,
    update_person_gender_from_household_browser,
)
from .views.household_browser_views import (
    household_browser,
    household_memorial_list,
    memorial_sheet,
)
from .views.household_create_views import create_household
from .views.household_edit_views import (
    edit_household,
    mark_household_extinct_view,
    replace_virtual_head,
)
from .views.household_head_transition_views import (
    household_head_transition,
    move_household_head_to_current,
    move_household_head_to_memorial,
)
from .views.household_information_views import print_household_information
from .views.household_person_views import (
    create_household_current_person,
    create_household_memorial_person,
    edit_person,
    move_memorial_person_household,
    person_memorial_transition,
)
from .views.memorial_distribution import memorial_distribution, memorial_distribution_print
from .views.memorial_notice_views import memorial_notices
from .views.memorial_sheet_fonts import memorial_sheet_font_css, memorial_sheet_font_file
from .views.offering_payment_views import (
    create_household_offering_payment,
    create_person_offering_payment,
    edit_household_offering_payment,
)
from .views.person_search_views import person_search
from .views.print_hub import print_hub
from .views.quality import (
    data_quality,
    data_science,
    data_science_content,
    death_demographics_csv,
    memo_tag_catalog,
    record_history,
    special_searches,
    universal_search,
)
from .views.service_ledger_views import print_service_schedule, service_ledger
from .views.service_schedule_candidate_views import (
    cancel_memorial_candidate,
    record_candidate_with_funeral,
)
from .views.service_schedule_create_views import create_service_schedule
from .views.service_schedule_edit_views import edit_service_schedule
from .views.settings_backup_admin import (
    backup_migration_guide,
    backup_settings,
    download_backup_migration_bundle,
    run_backup_now,
    verify_backup_now,
)
from .views.settings_data_imports import data_imports
from .views.settings_district_admin import districts
from .views.settings_district_member_sheets import (
    district_member_sheets,
    district_member_sheets_print,
)
from .views.settings_google_calendar_admin import (
    google_calendar_bulk_sync_status,
    google_calendar_settings,
)
from .views.settings_hand_delivery_head_actions import (
    replace_hand_delivery_household_head,
)
from .views.settings_hand_delivery_household_actions import (
    create_hand_delivery_review_household,
    rollback_created_hand_delivery_review_household,
)
from .views.settings_hand_delivery_review_views import (
    hand_delivery_review,
    import_hand_delivery_districts,
)
from .views.settings_handoff_admin import download_handoff_package
from .views.settings_home_admin import (
    save_temple_identity,
    save_ui_appearance,
    settings_home,
)
from .views.settings_household_delivery import household_districts
from .views.settings_membership_fees import (
    annual_membership_fee_check_sheet_scan_detail,
    annual_membership_fee_check_sheet_scan_file,
    annual_membership_fee_check_sheets,
    annual_membership_fee_postal_scan_file,
    annual_membership_fee_postal_scans,
    annual_membership_fee_receipts,
    annual_membership_fees,
)
from .views.settings_officer_rosters import (
    district_officer_roster,
    monto_sodai_roster,
    remove_person_role,
    responsible_officer_roster,
)
from .views.settings_postal_head_actions import (
    replace_postal_household_head,
)
from .views.settings_postal_household_actions import (
    create_postal_review_household,
    rollback_created_postal_review_household,
)
from .views.settings_postal_override_actions import (
    assign_postal_override,
)
from .views.settings_postal_reports import (
    district_officer_delivery_labels,
    district_officer_postal_labels,
    monto_sodai_postal_labels,
    postal_compare,
    postal_labels,
)
from .views.settings_postal_review_views import (
    import_postal_assignments,
    postal_review,
)
from .views.settings_schema_map import schema_map
from .views.settings_starter_admin import download_starter_package
from .views.settings_user_management import user_management
from .views.temple_events import edit_temple_event, temple_events

app_name = "office"


def protected(route, view, kwargs=None, name=None):
    return path(route, login_required(view), kwargs=kwargs, name=name)


urlpatterns = [
    protected("", home, name="home"),
    protected("home/services/<int:schedule_id>/complete/", complete_service_from_home, name="complete_service_from_home"),
    protected("temple-events/", temple_events, name="temple_events"),
    protected("temple-events/new/", edit_temple_event, name="create_temple_event"),
    protected("temple-events/<int:event_id>/", edit_temple_event, name="edit_temple_event"),
    protected("settings/", settings_home, name="settings_home"),
    protected("settings/accounting/", accounting, name="accounting"),
    protected("settings/nokotsudan-accounting/", nokotsudan_accounting, name="nokotsudan_accounting"),
    protected("settings/schema-map/", schema_map, name="schema_map"),
    protected("settings/temple-identity/", save_temple_identity, name="save_temple_identity"),
    protected("settings/ui-appearance/", save_ui_appearance, name="save_ui_appearance"),
    protected(
        "settings/handoff-package/download/",
        download_handoff_package,
        name="download_handoff_package",
    ),
    protected(
        "settings/starter-package/download/",
        download_starter_package,
        name="download_starter_package",
    ),
    protected("settings/users/", user_management, name="user_management"),
    protected("settings/data-imports/", data_imports, name="data_imports"),
    protected("settings/backup/", backup_settings, name="backup_settings"),
    protected(
        "settings/backup/migration/",
        backup_migration_guide,
        name="backup_migration_guide",
    ),
    protected("settings/backup/run/", run_backup_now, name="run_backup_now"),
    protected("settings/backup/verify/", verify_backup_now, name="verify_backup_now"),
    protected(
        "settings/backup/migration/bundle/",
        download_backup_migration_bundle,
        name="download_backup_migration_bundle",
    ),
    protected("settings/google-calendar/", google_calendar_settings, name="google_calendar_settings"),
    protected(
        "settings/google-calendar/bulk-sync-status/",
        google_calendar_bulk_sync_status,
        name="google_calendar_bulk_sync_status",
    ),
    protected(
        "settings/annual-membership-fees/",
        annual_membership_fees,
        name="annual_membership_fees",
    ),
    protected(
        "settings/annual-membership-fees/receipts/",
        annual_membership_fee_receipts,
        name="annual_membership_fee_receipts",
    ),
    protected(
        "settings/annual-membership-fees/check-sheets/",
        annual_membership_fee_check_sheets,
        name="annual_membership_fee_check_sheets",
    ),
    protected(
        "settings/annual-membership-fees/check-sheets/scans/<int:scan_id>/",
        annual_membership_fee_check_sheet_scan_detail,
        name="annual_membership_fee_check_sheet_scan_detail",
    ),
    protected(
        "settings/annual-membership-fees/check-sheets/scans/<int:scan_id>/file/",
        annual_membership_fee_check_sheet_scan_file,
        name="annual_membership_fee_check_sheet_scan_file",
    ),
    protected(
        "settings/annual-membership-fees/postal-scans/",
        annual_membership_fee_postal_scans,
        name="annual_membership_fee_postal_scans",
    ),
    protected(
        "settings/annual-membership-fees/postal-scans/<int:scan_id>/<str:kind>/",
        annual_membership_fee_postal_scan_file,
        name="annual_membership_fee_postal_scan_file",
    ),
    protected(
        "settings/import-hand-delivery-districts/",
        import_hand_delivery_districts,
        name="import_hand_delivery_districts",
    ),
    protected(
        "settings/hand-delivery-review/",
        hand_delivery_review,
        name="hand_delivery_review",
    ),
    protected(
        "settings/hand-delivery-review/replace-head/",
        replace_hand_delivery_household_head,
        name="replace_hand_delivery_household_head",
    ),
    protected(
        "settings/hand-delivery-review/create-household/",
        create_hand_delivery_review_household,
        name="create_hand_delivery_review_household",
    ),
    protected(
        "settings/hand-delivery-review/rollback-created-household/",
        rollback_created_hand_delivery_review_household,
        name="rollback_created_hand_delivery_review_household",
    ),
    protected(
        "settings/import-postal-assignments/",
        import_postal_assignments,
        name="import_postal_assignments",
    ),
    protected(
        "settings/postal-review/",
        postal_review,
        name="postal_review",
    ),
    protected(
        "settings/postal-compare/",
        postal_compare,
        name="postal_compare",
    ),
    protected(
        "settings/postal-labels/",
        postal_labels,
        name="postal_labels",
    ),
    protected(
        "settings/district-officer-postal-labels/",
        district_officer_postal_labels,
        name="district_officer_postal_labels",
    ),
    protected(
        "settings/monto-sodai-postal-labels/",
        monto_sodai_postal_labels,
        name="monto_sodai_postal_labels",
    ),
    protected(
        "settings/district-officer-delivery-labels/",
        district_officer_delivery_labels,
        name="district_officer_delivery_labels",
    ),
    protected(
        "settings/district-member-sheets/",
        district_member_sheets,
        name="district_member_sheets",
    ),
    protected(
        "settings/district-member-sheets/print/",
        district_member_sheets_print,
        name="district_member_sheets_print",
    ),
    protected(
        "settings/district-officers/",
        district_officer_roster,
        name="district_officer_roster",
    ),
    protected(
        "settings/responsible-officers/",
        responsible_officer_roster,
        name="responsible_officer_roster",
    ),
    protected(
        "settings/monto-sodai/",
        monto_sodai_roster,
        name="monto_sodai_roster",
    ),
    protected(
        "settings/remove-role/",
        remove_person_role,
        name="remove_person_role",
    ),
    protected(
        "settings/postal-review/replace-head/",
        replace_postal_household_head,
        name="replace_postal_household_head",
    ),
    protected(
        "settings/postal-review/assign-override/",
        assign_postal_override,
        name="assign_postal_override",
    ),
    protected(
        "settings/postal-review/create-household/",
        create_postal_review_household,
        name="create_postal_review_household",
    ),
    protected(
        "settings/postal-review/rollback-created-household/",
        rollback_created_postal_review_household,
        name="rollback_created_postal_review_household",
    ),
    protected("settings/districts/", districts, name="districts"),
    protected("settings/household-districts/", household_districts, name="household_districts"),
    protected("prints/", print_hub, name="print_hub"),
    protected("fonts/memorial-sheet.css", memorial_sheet_font_css, name="memorial_sheet_font_css"),
    protected(
        "fonts/memorial-sheet/<str:font_slug>.ttf",
        memorial_sheet_font_file,
        name="memorial_sheet_font_file",
    ),
    protected("households/", household_browser, name="household_browser"),
    protected("households/new/", create_household, name="create_household"),
    protected("people/", person_search, name="person_search"),
    protected("search-all/", universal_search, name="universal_search"),
    protected("memo-tags/", memo_tag_catalog, name="memo_tag_catalog"),
    protected("searches/", special_searches, name="special_searches"),
    protected("services/", service_ledger, name="service_ledger"),
    protected("memorial-notices/", memorial_notices, name="memorial_notices"),
    protected("memorial-distribution/", memorial_distribution, name="memorial_distribution"),
    protected("memorial-distribution/print/", memorial_distribution_print, name="memorial_distribution_print"),
    protected("households/<str:household_id>/edit/", edit_household, name="edit_household"),
    protected("households/<str:household_id>/print/", print_household_information, name="print_household_information"),
    protected(
        "households/<str:household_id>/memorial-list/",
        household_memorial_list,
        name="household_memorial_list",
    ),
    protected(
        "households/<str:household_id>/new-current-person/",
        create_household_current_person,
        name="create_household_current_person",
    ),
    protected(
        "households/<str:household_id>/new-memorial-person/",
        create_household_memorial_person,
        name="create_household_memorial_person",
    ),
    protected(
        "households/<str:household_id>/head-transition/",
        household_head_transition,
        name="household_head_transition",
    ),
    protected(
        "households/<str:household_id>/replace-virtual-head/",
        replace_virtual_head,
        name="replace_virtual_head",
    ),
    protected(
        "households/<str:household_id>/mark-extinct/",
        mark_household_extinct_view,
        name="mark_household_extinct",
    ),
    protected(
        "households/<str:household_id>/move-head-to-current/",
        move_household_head_to_current,
        name="move_household_head_to_current",
    ),
    protected(
        "households/<str:household_id>/move-head-to-memorial/",
        move_household_head_to_memorial,
        name="move_household_head_to_memorial",
    ),
    protected(
        "households/<str:household_id>/update-delivery/",
        update_household_delivery_assignment,
        name="update_household_delivery_assignment",
    ),
    protected(
        "households/<str:household_id>/clear-address-line2/",
        clear_household_address_line2,
        name="clear_household_address_line2",
    ),
    protected(
        "households/<str:household_id>/persons/<str:person_id>/edit/",
        edit_person,
        name="edit_person",
    ),
    protected(
        "households/<str:household_id>/persons/<str:person_id>/memorial-transition/",
        person_memorial_transition,
        name="person_memorial_transition",
    ),
    protected(
        "households/<str:household_id>/persons/<str:person_id>/move-household/",
        move_memorial_person_household,
        name="move_memorial_person_household",
    ),
    protected(
        "households/<str:household_id>/persons/<str:person_id>/update-gender/",
        update_person_gender_from_household_browser,
        name="update_person_gender_from_household_browser",
    ),
    protected(
        "households/<str:household_id>/persons/<str:person_id>/delete-from-same-name-candidates/",
        delete_person_from_same_name_candidates,
        name="delete_person_from_same_name_candidates",
    ),
    protected(
        "people/update-gender-batch/",
        bulk_update_people_gender,
        name="bulk_update_people_gender",
    ),
    protected(
        "households/<str:household_id>/persons/<str:person_id>/toggle-memorial-notice-opt-out/",
        toggle_person_memorial_notice_opt_out,
        name="toggle_person_memorial_notice_opt_out",
    ),
    protected(
        "households/<str:household_id>/payments/new/",
        create_household_offering_payment,
        name="create_household_offering_payment",
    ),
    protected(
        "households/<str:household_id>/payments/<int:payment_id>/edit/",
        edit_household_offering_payment,
        name="edit_household_offering_payment",
    ),
    protected(
        "households/<str:household_id>/events/<str:event_id>/edit/",
        edit_service_schedule,
        name="edit_service_schedule",
    ),
    protected(
        "households/<str:household_id>/events/<str:event_id>/print/",
        print_service_schedule,
        name="print_service_schedule",
    ),
    protected(
        "households/<str:household_id>/persons/<str:person_id>/services/new/",
        create_service_schedule,
        name="create_service_schedule",
    ),
    protected(
        "households/<str:household_id>/persons/<str:person_id>/payments/new/",
        create_person_offering_payment,
        name="create_person_offering_payment",
    ),
    protected(
        "households/<str:household_id>/persons/<str:person_id>/services/cancel/",
        cancel_memorial_candidate,
        name="cancel_memorial_candidate",
    ),
    protected(
        "households/<str:household_id>/persons/<str:person_id>/services/record-with-funeral/",
        record_candidate_with_funeral,
        name="record_candidate_with_funeral",
    ),
    protected("issues/", data_quality, name="data_quality"),
    protected("analytics/", data_science, name="data_science"),
    protected("analytics/content/", data_science_content, name="data_science_content"),
    protected(
        "analytics/death-demographics.csv/",
        death_demographics_csv,
        name="death_demographics_csv",
    ),
    protected("history/", record_history, name="record_history"),
    protected(
        "households/<str:household_id>/persons/<str:person_id>/memorial-sheet/",
        memorial_sheet,
        name="memorial_sheet",
    ),
]
