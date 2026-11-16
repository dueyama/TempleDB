from __future__ import annotations

from django.contrib import admin

from .models import (
    DatabaseBackupRun,
    DatabaseBackupSetting,
    DatabaseBackupVerificationRun,
    GoogleCalendarSyncSetting,
    TempleIdentitySetting,
)


@admin.register(DatabaseBackupSetting)
class DatabaseBackupSettingAdmin(admin.ModelAdmin):
    list_display = (
        "singleton_key",
        "destination_path",
        "daily_enabled",
        "weekly_verification_enabled",
        "retention_count",
        "last_scheduled_attempt_on",
        "last_scheduled_attempt_engine",
        "last_status",
        "last_completed_at",
    )


@admin.register(DatabaseBackupRun)
class DatabaseBackupRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "database_engine",
        "trigger_kind",
        "status",
        "database_name",
        "backup_file_name",
        "started_at",
        "finished_at",
    )
    list_filter = ("database_engine", "trigger_kind", "status")
    search_fields = ("backup_file_name", "backup_file_path", "error_message", "requested_by_label")


@admin.register(TempleIdentitySetting)
class TempleIdentitySettingAdmin(admin.ModelAdmin):
    list_display = (
        "singleton_key",
        "temple_sect",
        "temple_name",
        "temple_postal_code",
        "temple_phone",
        "chief_priest_name",
        "updated_at",
    )


@admin.register(GoogleCalendarSyncSetting)
class GoogleCalendarSyncSettingAdmin(admin.ModelAdmin):
    list_display = ("singleton_key", "enabled", "calendar_id", "updated_at")
    readonly_fields = ("base_url", "external_base_url")


@admin.register(DatabaseBackupVerificationRun)
class DatabaseBackupVerificationRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "backup_run",
        "trigger_kind",
        "status",
        "verification_database_name",
        "started_at",
        "finished_at",
    )
    list_filter = ("trigger_kind", "status")
    search_fields = ("verification_database_name", "error_message", "requested_by_label")
