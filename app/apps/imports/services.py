from __future__ import annotations

from datetime import date
from pathlib import Path

# Preserve the established cold-import order of this large compatibility façade;
# owner modules are exposed module-qualified and include monkeypatch seams.
# isort: off
from . import (
    auxiliary_hand_delivery,
    auxiliary_postal,
    data_quality_runtime,
    district_authority,
    district_delivery_labels,
    district_member_sheets,
    district_officer_rosters,
    household_browser_dataset_runtime,
    household_profile_runtime,
    household_head_runtime,
    household_browser,
    household_memorial_candidates_runtime,
    kana_cleanup_runtime,
    memorial_notice_runtime,
    memorial_shared,
    memorial_sheet_runtime,
    monto_sodai_analysis,
    monto_sodai_reports,
    monto_sodai_sources,
    pipeline_runtime,
    quality_reports,
    service_ledger_runtime,
    special_search_runtime,
    source_runtime,
)
# isort: on
from .models import (
    LEDGER_CATEGORY_WOMENS_ASSOCIATION,
)

build_household_browser_context = household_browser.build_household_browser_context
build_memorial_notice_context = memorial_notice_runtime.build_memorial_notice_context
build_memorial_sheet_context = memorial_sheet_runtime.build_memorial_sheet_context
build_service_ledger_context = service_ledger_runtime.build_service_ledger_context
build_data_quality_context = data_quality_runtime.build_data_quality_context
build_special_search_context = quality_reports.build_special_search_context
build_data_science_context = quality_reports.build_data_science_context

NULL_TOKEN = "__MDB_NULL__"
SPECIAL_SEARCH_DEFINITIONS = special_search_runtime.SPECIAL_SEARCH_DEFINITIONS
HAND_DELIVERY_DIRECTORY_PREFIX = "門徒名簿_"
HAND_DELIVERY_FILE_NAME = "手配り-表1.csv"
HAND_DELIVERY_SKIP_DISTRICTS = {"正", "畑"}
POSTAL_FILE_NAME = "郵送（遠隔地門徒＋婦人会）-表1.csv"
MONTO_SODAI_FILE_NAME = "総代-表1.csv"
POSTAL_SKIP_CLASSIFICATIONS: set[str] = set()
POSTAL_IMPORTED_LEDGER_CATEGORY_BY_CLASSIFICATION = {
    "F": LEDGER_CATEGORY_WOMENS_ASSOCIATION,
}
POSTAL_COMPARE_FIELDS = [
    ("recipient_name", "氏名"),
    ("postal_code", "郵便番号"),
    ("address_line1", "住所1"),
    ("address_line2", "住所2"),
    ("phone", "電話"),
]
LEGACY_IMPORTED_SCHEDULE_SOURCE_TABLES = {
    "UTM010_予定明細",
    "UTY020_初盆予定作成",
}
VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE = household_head_runtime.VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE
VIRTUAL_HOUSEHOLD_HEAD_RELATIONSHIP_LABEL = "仮戸主"
VIRTUAL_HOUSEHOLD_HEAD_NAME_PREFIX = "仮戸主 #P"
VIRTUAL_HOUSEHOLD_HEAD_KANA = "かりこしゅ"
PIPELINE_STEP_DEFINITIONS = pipeline_runtime.PIPELINE_STEP_DEFINITIONS
HOUSEHOLD_KANA_GROUPS = [
    {"key": "all", "label": "全", "description": "すべて"},
    {"key": "a", "label": "あ", "description": "あ行"},
    {"key": "ka", "label": "か", "description": "か行"},
    {"key": "sa", "label": "さ", "description": "さ行"},
    {"key": "ta", "label": "た", "description": "た行"},
    {"key": "na", "label": "な", "description": "な行"},
    {"key": "ha", "label": "は", "description": "は行"},
    {"key": "ma", "label": "ま", "description": "ま行"},
    {"key": "ya", "label": "や", "description": "や行"},
    {"key": "ra", "label": "ら", "description": "ら行"},
    {"key": "wa", "label": "わ", "description": "わ行"},
    {"key": "digit", "label": "0-9", "description": "数字"},
    {"key": "other", "label": "他", "description": "その他"},
]
HOUSEHOLD_KANA_GROUP_LABELS = {
    item["key"]: item["description"] for item in HOUSEHOLD_KANA_GROUPS
}
HOUSEHOLD_KANA_GROUP_KEYS = {item["key"] for item in HOUSEHOLD_KANA_GROUPS}
MEMORIAL_RANKS = [1, 3, 7, 13, 17, 25, 33, 50]
KIJITSU_STEPS = [
    {"label": "初七日", "offset_days": 6},
    {"label": "二七日", "offset_days": 13},
    {"label": "三七日", "offset_days": 20},
    {"label": "四七日", "offset_days": 27},
    {"label": "五七日", "offset_days": 34},
    {"label": "六七日", "offset_days": 41},
    {"label": "満中陰（四十九日）", "offset_days": 48},
    {"label": "百ヶ日", "offset_days": 99},
]
WEEKDAYS_JA = ["日", "月", "火", "水", "木", "金", "土"]
ANALYTICS_YEAR_LOWER_QUANTILE = 0.02
DEATH_INTERVAL_BUCKETS = [
    {"label": "0日", "minimum": 0, "maximum": 0},
    {"label": "1-6日", "minimum": 1, "maximum": 6},
    {"label": "7-13日", "minimum": 7, "maximum": 13},
    {"label": "14-29日", "minimum": 14, "maximum": 29},
    {"label": "30-89日", "minimum": 30, "maximum": 89},
    {"label": "90-179日", "minimum": 90, "maximum": 179},
    {"label": "180-364日", "minimum": 180, "maximum": 364},
    {"label": "365日以上", "minimum": 365, "maximum": None},
]
GENDER_LABELS = ["男", "女", "不明"]
GENDER_COLOR_MAP = {
    "男": "#4a6fa5",
    "女": "#c96a80",
    "不明": "#938777",
}
AVERAGE_AGE_TREND_LABELS = ["合計", "男", "女"]
AVERAGE_AGE_TREND_COLOR_MAP = {
    "合計": "#5d4631",
    "男": "#4a6fa5",
    "女": "#c96a80",
}
AVERAGE_AGE_TREND_WINDOW_YEARS = 5
AVERAGE_AGE_OUTLIER_IQR_MULTIPLIER = 1.5
COHORT_MODE_OPTIONS = [
    {"value": "share", "label": "構成比"},
    {"value": "count", "label": "実件数"},
]
HOMYO_INGO_SUFFIXES = ("院", "庵", "軒")
HOMYO_INGO_TYPE_LABELS = ["院", "庵", "軒", "院号なし"]
HOMYO_INGO_TYPE_COLORS = {
    "院": "#a65233",
    "庵": "#cf8d2e",
    "軒": "#6d8a49",
    "院号なし": "#9a9388",
}
HOMYO_PREFIX_TOKENS = ("釋尼", "釈尼", "釋", "釈", "尼")
MEMORIAL_NOTICE_COLUMNS_PER_PAGE = 10
MEMORIAL_NOTICE_ROWS_PER_PAGE = memorial_notice_runtime.MEMORIAL_NOTICE_ROWS_PER_PAGE
DEFAULT_MEMORIAL_NOTICE_INTRO_TEXT = memorial_notice_runtime.DEFAULT_MEMORIAL_NOTICE_INTRO_TEXT
DEFAULT_MEMORIAL_NOTICE_OUTRO_TEXT = memorial_notice_runtime.DEFAULT_MEMORIAL_NOTICE_OUTRO_TEXT
DEFAULT_MEMORIAL_NOTICE_SIGNATURE_TEXT = memorial_notice_runtime.DEFAULT_MEMORIAL_NOTICE_SIGNATURE_TEXT
DEFAULT_MEMORIAL_NOTICE_STYLE = memorial_notice_runtime.DEFAULT_MEMORIAL_NOTICE_STYLE
ERA_STARTS = [
    {"name": "令和", "start": date(2019, 5, 1)},
    {"name": "平成", "start": date(1989, 1, 8)},
    {"name": "昭和", "start": date(1926, 12, 25)},
    {"name": "大正", "start": date(1912, 7, 30)},
    {"name": "明治", "start": date(1868, 1, 25)},
]
KANJI_DIGITS = {
    0: "",
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
}


CommandResult = pipeline_runtime.CommandResult


def list_auxiliary_hand_delivery_csv_candidates() -> list[dict]:
    return auxiliary_hand_delivery.list_auxiliary_hand_delivery_csv_candidates()


def latest_auxiliary_hand_delivery_csv_path(folder_name: str | None = None) -> Path | None:
    return auxiliary_hand_delivery.latest_auxiliary_hand_delivery_csv_path(folder_name)


def list_auxiliary_postal_csv_candidates() -> list[dict]:
    return auxiliary_postal.list_auxiliary_postal_csv_candidates()


def latest_auxiliary_postal_csv_path(folder_name: str | None = None) -> Path | None:
    return auxiliary_postal.latest_auxiliary_postal_csv_path(folder_name)


def list_auxiliary_monto_sodai_csv_candidates() -> list[dict]:
    return monto_sodai_sources.list_auxiliary_monto_sodai_csv_candidates()


def latest_auxiliary_monto_sodai_csv_path(folder_name: str | None = None) -> Path | None:
    return monto_sodai_sources.latest_auxiliary_monto_sodai_csv_path(folder_name)


_district_officer_person_from_household = district_authority._district_officer_person_from_household
_district_profile_map_for_households = district_authority._district_profile_map_for_households
district_profile_for_person = district_authority.district_profile_for_person
person_can_be_district_officer = district_authority.person_can_be_district_officer
clear_district_officer_flags_for_household = district_authority.clear_district_officer_flags_for_household
clear_district_officer_flags_for_district = district_authority.clear_district_officer_flags_for_district
assign_district_officer_to_person = district_authority.assign_district_officer_to_person
district_officer_people_for_batch = district_authority.district_officer_people_for_batch
district_officer_people_by_district = district_authority.district_officer_people_by_district
district_officer_person_for_district = district_authority.district_officer_person_for_district

person_authority_audit = household_head_runtime.person_authority_audit
sync_household_head_snapshot_from_person = household_head_runtime.sync_household_head_snapshot_from_person
create_manual_household_head_person_from_snapshot = (
    household_head_runtime.create_manual_household_head_person_from_snapshot
)
create_virtual_household_head_person = household_head_runtime.create_virtual_household_head_person
sync_household_head_authority = household_head_runtime.sync_household_head_authority
_next_virtual_household_head_number = household_head_runtime._next_virtual_household_head_number


normalize_runtime_kana_storage = kana_cleanup_runtime.normalize_runtime_kana_storage
_format_kana_normalization_summary = kana_cleanup_runtime._format_kana_normalization_summary
cleanup_runtime_manual_candidate_schedules = kana_cleanup_runtime.cleanup_runtime_manual_candidate_schedules
_format_manual_candidate_cleanup_summary = kana_cleanup_runtime._format_manual_candidate_cleanup_summary


def import_hand_delivery_district_assignments(
    source_id: str,
    *,
    folder_name: str | None = None,
    editor_label: str = "",
    change_note: str = "",
) -> dict:
    return auxiliary_hand_delivery.import_hand_delivery_district_assignments(
        source_id,
        folder_name=folder_name,
        editor_label=editor_label,
        change_note=change_note,
    )


def analyze_hand_delivery_district_rows(source_id: str, *, folder_name: str | None = None) -> dict:
    return auxiliary_hand_delivery.analyze_hand_delivery_district_rows(
        source_id,
        folder_name=folder_name,
    )


def import_postal_assignments(
    source_id: str, *, folder_name: str | None = None,
    editor_label: str = "", change_note: str = "",
) -> dict:
    return auxiliary_postal.import_postal_assignments(
        source_id, folder_name=folder_name, editor_label=editor_label, change_note=change_note,
    )


def analyze_monto_sodai_rows(source_id: str, *, folder_name: str | None = None) -> dict:
    return monto_sodai_analysis.analyze_monto_sodai_rows(source_id, folder_name=folder_name)


def import_monto_sodai_assignments(
    source_id: str,
    *,
    folder_name: str | None = None,
    editor_label: str = "",
    change_note: str = "",
) -> dict:
    return monto_sodai_analysis.import_monto_sodai_assignments(
        source_id,
        folder_name=folder_name,
        editor_label=editor_label,
        change_note=change_note,
    )


def analyze_postal_rows(source_id: str, *, folder_name: str | None = None) -> dict:
    return auxiliary_postal.analyze_postal_rows(source_id, folder_name=folder_name)


def build_postal_compare_context(source_id: str, *, folder_name: str | None = None) -> dict:
    return auxiliary_postal.build_postal_compare_context(source_id, folder_name=folder_name)


def build_postal_label_context(
    source_id: str,
    *,
    include_memorial_notice_marker: bool = False,
) -> dict:
    return auxiliary_postal.build_postal_label_context(
        source_id,
        include_memorial_notice_marker=include_memorial_notice_marker,
    )


def build_district_officer_postal_label_context(source_id: str) -> dict:
    return auxiliary_postal.build_district_officer_postal_label_context(source_id)


build_monto_sodai_postal_label_context = monto_sodai_reports.build_monto_sodai_postal_label_context


build_district_officer_delivery_label_context = (
    district_delivery_labels.build_district_officer_delivery_label_context
)


build_district_member_sheet_context = district_member_sheets.build_district_member_sheet_context


build_district_officer_roster_context = district_officer_rosters.build_district_officer_roster_context
build_responsible_officer_roster_context = district_officer_rosters.build_responsible_officer_roster_context


def build_monto_sodai_roster_context(source_id: str, *, folder_name: str | None = None) -> dict:
    return monto_sodai_reports.build_monto_sodai_roster_context(source_id, folder_name=folder_name)


def search_households_for_postal_review(source_id: str, query: str, *, limit: int = 20) -> list[dict]:
    return auxiliary_postal.search_households_for_postal_review(source_id, query, limit=limit)


runtime_source_id = source_runtime.runtime_source_id
operational_source_id = source_runtime.operational_source_id
operational_source_status = source_runtime.operational_source_status
ensure_operational_source_record = source_runtime.ensure_operational_source_record
resolve_runtime_source_entry = source_runtime.resolve_runtime_source_entry
resolve_operational_source_entry = source_runtime.resolve_operational_source_entry
resolve_source_entry = source_runtime.resolve_source_entry
remove_registered_source = source_runtime.remove_registered_source
source_mdb_path = source_runtime.source_mdb_path
export_root = source_runtime.export_root
prepared_root = source_runtime.prepared_root
analysis_root = source_runtime.analysis_root
analysis_dir = source_runtime.analysis_dir
source_summary = source_runtime.source_summary
originaldb_root = source_runtime.originaldb_root
discover_source_files = source_runtime.discover_source_files
register_source_file = source_runtime.register_source_file
discover_originaldb_mdbs = source_runtime.discover_originaldb_mdbs
register_originaldb_source = source_runtime.register_originaldb_source
set_default_source = source_runtime.set_default_source
latest_export_snapshot = source_runtime.latest_export_snapshot


relationship_label_choices = household_profile_runtime.relationship_label_choices


latest_prepared_snapshot = source_runtime.latest_prepared_snapshot
analysis_summary = source_runtime.analysis_summary
latest_import_batch_summary = source_runtime.latest_import_batch_summary
latest_import_batch = source_runtime.latest_import_batch
import_batch_summary = source_runtime.import_batch_summary
latest_succeeded_import_batch = source_runtime.latest_succeeded_import_batch
pipeline_status_path = pipeline_runtime.pipeline_status_path
initial_pipeline_status = pipeline_runtime.initial_pipeline_status
write_pipeline_status = pipeline_runtime.write_pipeline_status
read_pipeline_status = pipeline_runtime.read_pipeline_status
execute_import_pipeline = pipeline_runtime.execute_import_pipeline
build_console_context = pipeline_runtime.build_console_context


run_action = pipeline_runtime.run_action
build_comparison_summary = pipeline_runtime.build_comparison_summary
build_row_preview = pipeline_runtime.build_row_preview


_load_household_browser_dataset = household_browser_dataset_runtime._load_household_browser_dataset
_load_household_browser_dataset_from_sqlite = household_browser_dataset_runtime._load_household_browser_dataset_from_sqlite
_build_memorial_candidates = household_memorial_candidates_runtime._build_memorial_candidates
_notice_eligible_memorial_members = household_memorial_candidates_runtime._notice_eligible_memorial_members
_attach_action_to_memorial_candidates = (
    household_memorial_candidates_runtime._attach_action_to_memorial_candidates
)
_decorate_memorial_members = household_memorial_candidates_runtime._decorate_memorial_members
_parse_input_date = household_memorial_candidates_runtime._parse_input_date
_add_memorial_years = household_memorial_candidates_runtime._add_memorial_years
_add_memorial_offset_years = household_memorial_candidates_runtime._add_memorial_offset_years
_memorial_offset_years_from_label = household_memorial_candidates_runtime._memorial_offset_years_from_label
_memorial_offset_years = household_memorial_candidates_runtime._memorial_offset_years
_first_obon_date = household_memorial_candidates_runtime._first_obon_date
_replace_year_clamped = household_memorial_candidates_runtime._replace_year_clamped
_to_wareki_date_numeric = memorial_shared._to_wareki_date_numeric
_effective_memorial_rules = memorial_shared._effective_memorial_rules


_service_row_from_model = service_ledger_runtime._service_row_from_model
_actual_service_schedule_death_date = service_ledger_runtime._actual_service_schedule_death_date
_resolved_service_schedule_target_date = service_ledger_runtime._resolved_service_schedule_target_date
_service_schedule_category_for_candidate_type = service_ledger_runtime._service_schedule_category_for_candidate_type


_kijitsu_offset_days_from_label = household_memorial_candidates_runtime._kijitsu_offset_days_from_label


_service_ledger_schedule_entry = service_ledger_runtime._service_ledger_schedule_entry


_collapse_linked_service_entries = service_ledger_runtime._collapse_linked_service_entries
_linked_service_entry_master_sort_key = service_ledger_runtime._linked_service_entry_master_sort_key


_effective_service_schedule_status = household_memorial_candidates_runtime._effective_service_schedule_status


_effective_service_schedule_status_label = service_ledger_runtime._effective_service_schedule_status_label


_effective_service_event_status = household_memorial_candidates_runtime._effective_service_event_status


_service_event_is_actual = service_ledger_runtime._service_event_is_actual
_is_actual_service_schedule = service_ledger_runtime._is_actual_service_schedule
_service_ledger_schedule_matches = service_ledger_runtime._service_ledger_schedule_matches
_service_ledger_candidate_matches = service_ledger_runtime._service_ledger_candidate_matches


_candidate_already_has_actual_schedule = service_ledger_runtime._candidate_already_has_actual_schedule


_matching_actual_schedule_for_candidate = service_ledger_runtime._matching_actual_schedule_for_candidate


_service_ledger_candidate_entry = service_ledger_runtime._service_ledger_candidate_entry


_person_is_service_target = household_memorial_candidates_runtime._person_is_service_target


_service_target_person_entry = service_ledger_runtime._service_target_person_entry
_service_target_person_matches = service_ledger_runtime._service_target_person_matches


_build_special_search_entries = special_search_runtime._build_special_search_entries
_household_profile_for_display = household_profile_runtime._household_profile_for_display
# These are the only top-level wrappers intentionally kept in this compatibility facade.
_TOP_LEVEL_WRAPPER_FUNCTION_EXPORTS = [
    "list_auxiliary_hand_delivery_csv_candidates",
    "latest_auxiliary_hand_delivery_csv_path",
    "list_auxiliary_postal_csv_candidates",
    "latest_auxiliary_postal_csv_path",
    "list_auxiliary_monto_sodai_csv_candidates",
    "latest_auxiliary_monto_sodai_csv_path",
    "import_hand_delivery_district_assignments",
    "analyze_hand_delivery_district_rows",
    "import_postal_assignments",
    "analyze_monto_sodai_rows",
    "import_monto_sodai_assignments",
    "analyze_postal_rows",
    "build_postal_compare_context",
    "build_postal_label_context",
    "build_district_officer_postal_label_context",
    "build_monto_sodai_roster_context",
    "search_households_for_postal_review",
]

_PUBLIC_RUNTIME_API_EXPORTS = [
    "SPECIAL_SEARCH_DEFINITIONS",
    "VIRTUAL_HOUSEHOLD_HEAD_SOURCE_TABLE",
    "analyze_hand_delivery_district_rows",
    "analyze_monto_sodai_rows",
    "analyze_postal_rows",
    "analysis_summary",
    "build_data_quality_context",
    "build_data_science_context",
    "build_district_member_sheet_context",
    "build_district_officer_delivery_label_context",
    "build_district_officer_postal_label_context",
    "build_district_officer_roster_context",
    "build_household_browser_context",
    "build_memorial_notice_context",
    "build_memorial_sheet_context",
    "build_monto_sodai_postal_label_context",
    "build_monto_sodai_roster_context",
    "build_postal_compare_context",
    "build_postal_label_context",
    "build_responsible_officer_roster_context",
    "build_service_ledger_context",
    "build_special_search_context",
    "create_virtual_household_head_person",
    "district_officer_people_by_district",
    "district_officer_people_for_batch",
    "district_profile_for_person",
    "discover_source_files",
    "execute_import_pipeline",
    "import_batch_summary",
    "import_hand_delivery_district_assignments",
    "import_monto_sodai_assignments",
    "import_postal_assignments",
    "latest_auxiliary_hand_delivery_csv_path",
    "latest_auxiliary_monto_sodai_csv_path",
    "latest_auxiliary_postal_csv_path",
    "latest_export_snapshot",
    "latest_import_batch",
    "latest_import_batch_summary",
    "latest_prepared_snapshot",
    "latest_succeeded_import_batch",
    "list_auxiliary_hand_delivery_csv_candidates",
    "list_auxiliary_monto_sodai_csv_candidates",
    "list_auxiliary_postal_csv_candidates",
    "normalize_runtime_kana_storage",
    "operational_source_id",
    "operational_source_status",
    "person_authority_audit",
    "register_source_file",
    "relationship_label_choices",
    "remove_registered_source",
    "ensure_operational_source_record",
    "resolve_operational_source_entry",
    "resolve_runtime_source_entry",
    "resolve_source_entry",
    "runtime_source_id",
    "search_households_for_postal_review",
    "source_summary",
    "sync_household_head_authority",
    "sync_household_head_snapshot_from_person",
]

_PRIVATE_COMPATIBILITY_ALIAS_EXPORTS = [
    "_build_memorial_candidates",
    "_build_special_search_entries",
    "_format_kana_normalization_summary",
    "_household_profile_for_display",
    "_load_household_browser_dataset",
    "_load_household_browser_dataset_from_sqlite",
    "_replace_year_clamped",
    "_resolved_service_schedule_target_date",
    "_to_wareki_date_numeric",
]

__all__ = [
    *_PUBLIC_RUNTIME_API_EXPORTS,
    *_PRIVATE_COMPATIBILITY_ALIAS_EXPORTS,
]
