from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.forms import TempleIdentitySettingForm, UiAppearancePreferenceForm
from apps.core.services import backup as backup_services
from apps.core.services import google_calendar as google_calendar_services
from apps.core.services import starter_package as starter_package_services
from apps.core.services import temple_identity as temple_identity_services
from apps.core.services import ui_appearance as ui_appearance_services
from apps.imports import canonical_population
from apps.imports.models import (
    HOUSEHOLD_DELIVERY_DISTRICT,
    HOUSEHOLD_DELIVERY_NONE,
    HOUSEHOLD_DELIVERY_POSTAL,
    District,
    GoogleCalendarSyncBinding,
    Household,
    HouseholdProfile,
    Person,
)
from apps.office import services
from apps.office.views.common import _ensure_superuser


def settings_home(request: HttpRequest) -> HttpResponse:
    active_source_id = services.operational_source_id()
    operational_source_status = services.operational_source_status()
    database_engine = backup_services.current_database_engine()
    backup_setting = backup_services.get_or_create_backup_setting()
    google_calendar_setting = google_calendar_services.get_or_create_google_calendar_sync_setting()
    google_calendar_account_info = google_calendar_services.google_calendar_service_account_info()
    temple_identity_setting = temple_identity_services.get_or_create_temple_identity_setting()
    ui_appearance_state = ui_appearance_services.ui_appearance_state()
    backup_last_success_run = backup_services.latest_successful_backup_run()
    backup_last_failure_run = backup_services.latest_failed_backup_run()
    User = get_user_model()
    provenance_batch = canonical_population.canonical_provenance_import_batch(
        source_id=active_source_id,
    )
    district_household_count = 0
    postal_household_count = 0
    no_delivery_household_count = 0
    unassigned_household_count = 0
    district_officer_count = 0
    responsible_officer_count = 0
    monto_sodai_count = 0
    latest_household_batch_id = ""
    if provenance_batch is not None:
        latest_household_batch_id = provenance_batch.prepared_snapshot_id
        district_officer_count = len(
            services.district_officer_people_for_batch(
                active_source_id,
                batch=provenance_batch,
            )
        )
        responsible_officer_count = Person.objects.filter(
            deleted_at__isnull=True,
            is_responsible_officer=True,
        ).count()
        monto_sodai_count = Person.objects.filter(
            deleted_at__isnull=True,
            is_monto_sodai=True,
        ).count()
        household_ids = list(
            Household.objects.filter(deleted_at__isnull=True).values_list(
                "household_uid",
                flat=True,
            )
        )
        profiles = list(
            HouseholdProfile.objects.filter(
                source__source_id=active_source_id,
                household_uid__in=household_ids,
            )
        )
        profile_map = {profile.household_uid: profile for profile in profiles}
        district_household_count = sum(
            1
            for household_id in household_ids
            if (
                profile_map.get(household_id) is not None
                and profile_map[household_id].delivery_method == HOUSEHOLD_DELIVERY_DISTRICT
                and profile_map[household_id].district_id is not None
            )
        )
        postal_household_count = sum(
            1
            for household_id in household_ids
            if (
                profile_map.get(household_id) is not None
                and profile_map[household_id].delivery_method == HOUSEHOLD_DELIVERY_POSTAL
            )
        )
        no_delivery_household_count = sum(
            1
            for household_id in household_ids
            if (
                profile_map.get(household_id) is not None
                and profile_map[household_id].delivery_method == HOUSEHOLD_DELIVERY_NONE
            )
        )
        unassigned_household_count = max(
            len(household_ids)
            - district_household_count
            - postal_household_count
            - no_delivery_household_count,
            0,
        )
    context = {
        "selected_source_id": active_source_id,
        "operational_source_status": operational_source_status,
        "district_count": District.objects.count(),
        "active_district_count": District.objects.filter(is_active=True).count(),
        "inactive_district_count": District.objects.filter(is_active=False).count(),
        "district_household_count": district_household_count,
        "postal_household_count": postal_household_count,
        "no_delivery_household_count": no_delivery_household_count,
        "unassigned_household_count": unassigned_household_count,
        "district_officer_count": district_officer_count,
        "responsible_officer_count": responsible_officer_count,
        "monto_sodai_count": monto_sodai_count,
        "latest_household_batch_id": latest_household_batch_id,
        "user_count": User._default_manager.count(),
        "active_user_count": User._default_manager.filter(is_active=True).count(),
        "admin_user_count": User._default_manager.filter(is_superuser=True).count(),
        "database_engine_label": {
            "postgresql": "PostgreSQL",
            "sqlite": "SQLite",
        }.get(database_engine, database_engine),
        "backup_feature_enabled": backup_services.is_database_backup_supported(),
        "backup_setting": backup_setting,
        "backup_destination_status": (
            backup_services.backup_destination_status_for_setting(backup_setting)
        ),
        "backup_last_success_run": backup_last_success_run,
        "backup_last_failure_run": backup_last_failure_run,
        "starter_package_available": starter_package_services.starter_package_available(),
        "google_calendar_setting": google_calendar_setting,
        "google_calendar_account_info": google_calendar_account_info,
        "google_calendar_configuration_errors": google_calendar_services.google_calendar_configuration_errors(
            google_calendar_setting
        ),
        "google_calendar_conflict_count": GoogleCalendarSyncBinding.objects.filter(
            sync_status=GoogleCalendarSyncBinding.SyncStatus.CONFLICT
        ).count(),
        "google_calendar_error_count": GoogleCalendarSyncBinding.objects.filter(
            sync_status=GoogleCalendarSyncBinding.SyncStatus.ERROR
        ).count(),
        "temple_identity_setting": temple_identity_setting,
        "temple_identity_form": TempleIdentitySettingForm(instance=temple_identity_setting),
        "ui_appearance_form": UiAppearancePreferenceForm(
            initial={"theme": ui_appearance_state.theme}
        ),
        "ui_theme_label": ui_appearance_services.UI_THEME_LABELS[
            ui_appearance_state.theme
        ],
        "ui_theme_warning": ui_appearance_state.error,
    }
    return render(request, "office/settings_home.html", context)


@require_POST
def save_temple_identity(request: HttpRequest) -> HttpResponse:
    setting = temple_identity_services.get_or_create_temple_identity_setting()
    form = TempleIdentitySettingForm(request.POST, instance=setting)
    if form.is_valid():
        form.save()
        messages.success(request, "寺院情報を保存しました。年忌表などの印刷へ反映されます。")
    else:
        first_error = next(iter(form.errors.values()))[0] if form.errors else "寺院情報を保存できませんでした。"
        messages.error(request, str(first_error))
    return redirect(f"{reverse('office:settings_home')}#temple-identity-card")


@require_POST
def save_ui_appearance(request: HttpRequest) -> HttpResponse:
    _ensure_superuser(request)
    form = UiAppearancePreferenceForm(request.POST)
    if form.is_valid():
        try:
            ui_appearance_services.save_ui_theme(form.cleaned_data["theme"])
        except ui_appearance_services.UiAppearanceError:
            messages.error(request, "表示テーマを保存できませんでした。保存先を確認してください。")
        else:
            messages.success(request, "表示テーマを保存しました。")
    else:
        first_error = (
            next(iter(form.errors.values()))[0]
            if form.errors
            else "表示テーマを保存できませんでした。"
        )
        messages.error(request, str(first_error))
    return redirect(f"{reverse('office:settings_home')}#ui-appearance-card")


__all__ = [
    "save_temple_identity",
    "save_ui_appearance",
    "settings_home",
]
