from __future__ import annotations

from django.contrib import admin

from .models import (
    AnnualMembershipFeeCheckSheetScan,
    AnnualMembershipFeePayment,
    AnnualMembershipFeePostalScan,
    AnnualMembershipFeeSetting,
    DeceasedProfile,
    District,
    ExportSnapshot,
    GoogleCalendarSyncBinding,
    Household,
    HouseholdProfile,
    ImportBatch,
    ImportIssue,
    LegacySource,
    MemoTag,
    MemoTagAssignment,
    OfferingPayment,
    Person,
    RecordEditLog,
    ServiceSchedule,
    VisitNote,
)


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "sort_order", "is_active", "updated_at")
    search_fields = ("name", "short_name", "notes")
    list_filter = ("is_active",)


@admin.register(HouseholdProfile)
class HouseholdProfileAdmin(admin.ModelAdmin):
    list_display = (
        "source",
        "legacy_household_id",
        "current_household_name",
        "delivery_method",
        "district",
        "updated_at",
    )
    search_fields = (
        "household_uid",
        "mailing_name",
        "district__name",
    )
    list_filter = ("source", "delivery_method", "district")

    @admin.display(description="legacy household id", ordering="household_uid")
    def legacy_household_id(self, obj: HouseholdProfile) -> str:
        return obj.household_uid

    @admin.display(description="戸主名")
    def current_household_name(self, obj: HouseholdProfile) -> str:
        return obj.household_name_snapshot


@admin.register(LegacySource)
class LegacySourceAdmin(admin.ModelAdmin):
    list_display = ("source_id", "label", "status", "is_primary", "updated_at")
    search_fields = ("source_id", "label", "file_path", "notes")
    list_filter = ("status", "is_primary")


@admin.register(ExportSnapshot)
class ExportSnapshotAdmin(admin.ModelAdmin):
    list_display = ("source", "snapshot_id", "table_count", "source_created_at", "updated_at")
    search_fields = ("source__source_id", "snapshot_id")
    list_filter = ("source",)


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = (
        "batch_uuid",
        "source",
        "prepared_snapshot_id",
        "scope",
        "mode",
        "status",
        "households_imported",
        "persons_imported",
        "service_schedules_imported",
        "issues_count",
        "created_at",
    )
    search_fields = ("batch_uuid", "source__source_id", "prepared_snapshot_id")
    list_filter = ("mode", "status", "scope", "source")


@admin.register(ImportIssue)
class ImportIssueAdmin(admin.ModelAdmin):
    list_display = ("batch", "severity", "code", "source_table", "source_row_number", "created_at")
    search_fields = ("code", "legacy_pk_text", "message")
    list_filter = ("severity", "code", "source_table")


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ("household_uid", "current_head_name", "ledger_category", "batch", "source_export_batch")
    search_fields = ("household_uid", "head_person__name", "head_person__kana", "phone", "email")
    list_filter = ("batch", "ledger_category")

    @admin.display(description="戸主名")
    def current_head_name(self, obj: Household) -> str:
        return obj.display_head_name()


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("person_uid", "name", "relationship_label", "household", "is_deceased")
    search_fields = ("person_uid", "name", "kana", "relationship_label")
    list_filter = ("batch", "is_deceased", "family_category")


@admin.register(DeceasedProfile)
class DeceasedProfileAdmin(admin.ModelAdmin):
    list_display = ("person", "death_date", "kaimyo", "hatsubon_flag")
    search_fields = ("person__name", "kaimyo")
    list_filter = ("hatsubon_flag", "memorial_notice_opt_out")


@admin.register(ServiceSchedule)
class ServiceScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "service_label",
        "household_name_snapshot",
        "subject_name",
        "scheduled_date",
        "status",
        "record_origin",
        "is_demo_data",
    )
    search_fields = (
        "service_label",
        "subject_name",
        "household_name_snapshot",
        "household_uid",
        "person_uid",
    )
    list_filter = ("category", "status", "record_origin", "is_demo_data", "source_table")


@admin.register(GoogleCalendarSyncBinding)
class GoogleCalendarSyncBindingAdmin(admin.ModelAdmin):
    list_display = (
        "sync_key",
        "calendar_id",
        "primary_schedule",
        "sync_status",
        "last_synced_at",
    )
    search_fields = ("sync_key", "calendar_id", "google_event_id", "last_error_message")
    list_filter = ("sync_status", "calendar_id")


@admin.register(VisitNote)
class VisitNoteAdmin(admin.ModelAdmin):
    list_display = ("title", "household_name_snapshot", "visited_on", "sync_state", "is_demo_data")
    search_fields = ("title", "body", "household_name_snapshot", "person_name_snapshot")
    list_filter = ("sync_state", "pinned_for_household", "is_demo_data")


@admin.register(OfferingPayment)
class OfferingPaymentAdmin(admin.ModelAdmin):
    list_display = (
        "household_name_snapshot",
        "amount",
        "payment_category",
        "payment_method",
        "received_on",
        "is_demo_data",
    )
    search_fields = ("household_name_snapshot", "person_name_snapshot", "received_by", "notes")
    list_filter = ("payment_category", "payment_method", "is_demo_data")


@admin.register(AnnualMembershipFeeSetting)
class AnnualMembershipFeeSettingAdmin(admin.ModelAdmin):
    list_display = ("source", "year", "default_amount", "updated_at")
    search_fields = ("source__source_id", "year", "note")
    list_filter = ("source", "year")


@admin.register(AnnualMembershipFeePayment)
class AnnualMembershipFeePaymentAdmin(admin.ModelAdmin):
    list_display = (
        "source",
        "year",
        "household_uid",
        "household_name_snapshot",
        "amount",
        "received_on",
        "is_exception",
    )
    search_fields = (
        "household_uid",
        "household_name_snapshot",
        "district_name_snapshot",
        "received_by",
        "note",
    )
    list_filter = ("source", "year", "delivery_method_snapshot", "district_name_snapshot", "is_exception")


@admin.register(AnnualMembershipFeeCheckSheetScan)
class AnnualMembershipFeeCheckSheetScanAdmin(admin.ModelAdmin):
    list_display = (
        "source",
        "year",
        "status",
        "original_filename",
        "uploaded_by",
        "created_at",
        "confirmed_by",
        "confirmed_at",
    )
    search_fields = (
        "original_filename",
        "file_storage_key",
        "file_sha256",
        "uploaded_by",
        "confirmed_by",
    )
    list_filter = ("source", "year", "status")


@admin.register(AnnualMembershipFeePostalScan)
class AnnualMembershipFeePostalScanAdmin(admin.ModelAdmin):
    list_display = (
        "source",
        "year",
        "status",
        "original_filename",
        "page_number",
        "page_count",
        "statement_date",
        "selected_legacy_household_id",
        "selected_household_name_snapshot",
        "confirmed_at",
    )
    search_fields = (
        "original_filename",
        "pdf_storage_key",
        "page_image_storage_key",
        "crop_storage_key",
        "pdf_sha256",
        "selected_household_uid",
        "selected_household_name_snapshot",
        "recognized_text",
    )
    list_filter = ("source", "year", "status")

    @admin.display(
        ordering="selected_household_uid",
        description="selected legacy household id",
    )
    def selected_legacy_household_id(
        self,
        scan: AnnualMembershipFeePostalScan,
    ) -> str:
        return scan.selected_household_uid


@admin.register(MemoTag)
class MemoTagAdmin(admin.ModelAdmin):
    list_display = ("label", "origin", "is_active", "updated_at")
    search_fields = ("label", "slug", "description")
    list_filter = ("origin", "is_active")


@admin.register(MemoTagAssignment)
class MemoTagAssignmentAdmin(admin.ModelAdmin):
    list_display = ("tag", "note_label", "note_type", "source_kind", "legacy_household_id", "updated_at")
    search_fields = (
        "tag__label",
        "note_label",
        "note_type",
        "legacy_household_id",
        "legacy_person_id",
        "legacy_schedule_id",
        "note_excerpt",
    )
    list_filter = ("source_kind", "note_type", "tag")


@admin.register(RecordEditLog)
class RecordEditLogAdmin(admin.ModelAdmin):
    list_display = (
        "record_type",
        "record_label",
        "legacy_household_id",
        "legacy_person_id",
        "legacy_schedule_id",
        "editor_label",
        "created_at",
    )
    search_fields = (
        "record_label",
        "legacy_household_id",
        "legacy_person_id",
        "legacy_schedule_id",
        "editor_label",
        "change_note",
    )
    list_filter = ("record_type", "legacy_source_id", "created_at")
