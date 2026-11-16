from __future__ import annotations

from django.db import models

from . import model_households, model_memorial_sync
from .models_shared import (
    HOUSEHOLD_DELIVERY_CHOICES,
    HouseholdHeadResolutionError,
    SoftDeleteMixin,
    TimestampedModel,
)


class HouseholdProfile(TimestampedModel):
    source = models.ForeignKey(
        "imports.LegacySource",
        on_delete=models.CASCADE,
        related_name="household_profiles",
    )
    household_uid = models.CharField(max_length=255)
    delivery_method = models.CharField(max_length=16, blank=True, choices=HOUSEHOLD_DELIVERY_CHOICES)
    general_notice_opt_out = models.BooleanField(null=True, blank=True)
    memorial_notice_opt_out = models.BooleanField(null=True, blank=True)
    district = models.ForeignKey(
        "imports.District",
        on_delete=models.SET_NULL,
        related_name="household_profiles",
        null=True,
        blank=True,
    )
    mailing_person_uid = models.CharField(max_length=255, blank=True)
    mailing_name = models.CharField(max_length=255, blank=True)
    mailing_postal_code = models.CharField(max_length=32, blank=True)
    mailing_address_line1 = models.CharField(max_length=255, blank=True)
    mailing_address_line2 = models.CharField(max_length=255, blank=True)
    mailing_phone = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["source__source_id", "household_uid"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "household_uid"],
                name="imports_householdprofile_unique_source_household",
            )
        ]

    def __str__(self) -> str:
        household = self.resolve_household()
        if household is not None:
            try:
                return household.display_head_name()
            except HouseholdHeadResolutionError:
                return household.household_uid
        return self.household_uid

    @property
    def legacy_household_id(self) -> str:
        """Compatibility alias for the previous instance attribute."""

        return self.household_uid

    @legacy_household_id.setter
    def legacy_household_id(self, value: str | None) -> None:
        self.household_uid = str(value or "")

    def resolve_household(self) -> Household | None:
        return model_households.resolve_household_for_profile(self)

    @property
    def mailing_person_legacy_person_id(self) -> str:
        """Compatibility alias for the previous instance attribute."""

        return self.mailing_person_uid

    @mailing_person_legacy_person_id.setter
    def mailing_person_legacy_person_id(self, value: str) -> None:
        self.mailing_person_uid = value

    @property
    def household_name_snapshot(self) -> str:
        return model_households.household_name_snapshot(self)

    @household_name_snapshot.setter
    def household_name_snapshot(self, value: str | None) -> None:
        model_households.set_household_name_snapshot(self, value)

    @property
    def household_name_kana_snapshot(self) -> str:
        return model_households.household_name_kana_snapshot(self)

    @household_name_kana_snapshot.setter
    def household_name_kana_snapshot(self, value: str | None) -> None:
        model_households.set_household_name_kana_snapshot(self, value)


class Household(SoftDeleteMixin, TimestampedModel):
    batch = models.ForeignKey(
        "imports.ImportBatch",
        on_delete=models.PROTECT,
        related_name="households",
    )
    legacy_source_id = models.CharField(max_length=100)
    source_mdb_file = models.TextField()
    source_export_batch = models.CharField(max_length=64)
    source_table = models.CharField(max_length=128, default="UTB001_戸主")
    source_row_number = models.PositiveIntegerField()
    legacy_pk_text = models.CharField(max_length=255)
    household_uid = models.CharField(max_length=255)
    head_person = models.ForeignKey(
        "imports.Person",
        on_delete=models.SET_NULL,
        related_name="headed_households",
        null=True,
        blank=True,
    )
    postal_code = models.CharField(max_length=32, blank=True)
    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    address_line3 = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=64, blank=True)
    fax = models.CharField(max_length=64, blank=True)
    mobile = models.CharField(max_length=64, blank=True)
    email = models.CharField(max_length=255, blank=True)
    steward_legacy_id = models.CharField(max_length=64, blank=True)
    ledger_category = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)
    raw_record = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["household_uid"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "household_uid"],
                name="imports_household_unique_batch_legacy_household",
            )
        ]

    @property
    def legacy_household_id(self) -> str:
        return self.household_uid

    @legacy_household_id.setter
    def legacy_household_id(self, value: str | None) -> None:
        self.household_uid = str(value or "")

    @staticmethod
    def _normalize_head_name_identity(value: str | None) -> str:
        return model_households.normalize_head_name_identity(value)

    @staticmethod
    def _normalize_head_kana_identity(value: str | None) -> str:
        return model_households.normalize_head_kana_identity(value)

    def snapshot_head_name(self) -> str:
        return model_households.snapshot_head_name(self)

    def snapshot_head_name_kana(self) -> str:
        return model_households.snapshot_head_name_kana(self)

    @property
    def head_name(self) -> str:
        if hasattr(self, "_head_name_override"):
            return str(self._head_name_override or "").strip()
        return self.resolved_head_name()

    @head_name.setter
    def head_name(self, value: str | None) -> None:
        self._head_name_override = (value or "").strip()

    @property
    def head_name_kana(self) -> str:
        if hasattr(self, "_head_name_kana_override"):
            return str(self._head_name_kana_override or "").strip()
        return self.resolved_head_name_kana()

    @head_name_kana.setter
    def head_name_kana(self, value: str | None) -> None:
        self._head_name_kana_override = (value or "").strip()

    def resolve_head_person(self) -> Person | None:
        return model_households.resolve_head_person(self)

    def resolved_head_name(self) -> str:
        return model_households.resolved_head_name(self)

    def resolved_head_name_kana(self) -> str:
        return model_households.resolved_head_name_kana(self)

    def require_head_person(self) -> Person:
        return model_households.require_head_person(self)

    def display_head_name(self) -> str:
        return model_households.display_head_name(self)

    def display_head_name_kana(self) -> str:
        return model_households.display_head_name_kana(self)

    def __str__(self) -> str:
        return self.display_head_name()

    def save(self, *args, **kwargs):  # type: ignore[override]
        return model_households.household_save(self, *args, **kwargs)

    def refresh_from_db(self, using=None, fields=None, from_queryset=None):  # type: ignore[override]
        return model_households.household_refresh_from_db(
            self,
            using=using,
            fields=fields,
            from_queryset=from_queryset,
        )


class Person(SoftDeleteMixin, TimestampedModel):
    batch = models.ForeignKey(
        "imports.ImportBatch",
        on_delete=models.PROTECT,
        related_name="persons",
    )
    household = models.ForeignKey(
        "imports.Household",
        on_delete=models.CASCADE,
        related_name="persons",
    )
    legacy_source_id = models.CharField(max_length=100)
    source_mdb_file = models.TextField()
    source_export_batch = models.CharField(max_length=64)
    source_table = models.CharField(max_length=128, default="UTB002_家族")
    source_row_number = models.PositiveIntegerField()
    legacy_pk_text = models.CharField(max_length=255)
    person_uid = models.CharField(max_length=255)
    name = models.CharField(max_length=255, blank=True)
    kana = models.CharField(max_length=255, blank=True)
    kana_is_auto_generated = models.BooleanField(default=False)
    relationship_label = models.CharField(max_length=64, blank=True)
    family_category = models.CharField(max_length=64, blank=True)
    gender = models.CharField(max_length=32, blank=True)
    is_district_officer = models.BooleanField(default=False)
    is_responsible_officer = models.BooleanField(default=False)
    is_monto_sodai = models.BooleanField(default=False)
    birth_date_raw = models.CharField(max_length=64, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    birth_date_parse_error = models.CharField(max_length=255, blank=True)
    person_note = models.TextField(blank=True)
    is_deceased = models.BooleanField(default=False)
    death_date_raw = models.CharField(max_length=64, blank=True)
    death_date = models.DateField(null=True, blank=True)
    death_date_parse_error = models.CharField(max_length=255, blank=True)
    kaimyo = models.CharField(max_length=255, blank=True)
    kaimyo_kana = models.CharField(max_length=255, blank=True)
    age_at_death_raw = models.CharField(max_length=32, blank=True)
    age_at_death = models.PositiveIntegerField(null=True, blank=True)
    age_unit = models.CharField(max_length=16, blank=True)
    legacy_hatsubon_flag = models.CharField(max_length=16, blank=True)
    hatsubon_flag = models.BooleanField(null=True, blank=True)
    memorial_notice_opt_out = models.BooleanField(null=True, blank=True)
    deceased_note = models.TextField(blank=True)
    memorial_payload = models.JSONField(default=dict, blank=True)
    raw_record = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["person_uid"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "person_uid"],
                name="imports_person_unique_batch_legacy_person",
            )
        ]

    @property
    def household_uid(self) -> str:
        household = self._state.fields_cache.get("household")
        if household is not None:
            return str(household.household_uid or "")
        if self.household_id:
            return str(self.household.household_uid or "")
        return str(getattr(self, "_household_uid_compat", "") or "")

    @household_uid.setter
    def household_uid(self, value: str | None) -> None:
        normalized_value = str(value or "")
        household = self._state.fields_cache.get("household")
        if (
            household is not None
            and normalized_value
            and normalized_value != str(household.household_uid or "")
        ):
            raise ValueError("Person household UID must match the related Household.")
        self._household_uid_compat = normalized_value

    @property
    def legacy_household_id(self) -> str:
        return self.household_uid

    @legacy_household_id.setter
    def legacy_household_id(self, value: str | None) -> None:
        self.household_uid = value

    @property
    def legacy_person_id(self) -> str:
        return self.person_uid

    @legacy_person_id.setter
    def legacy_person_id(self, value: str | None) -> None:
        self.person_uid = str(value or "")

    def __str__(self) -> str:
        return self.name or self.person_uid

    def has_memorial_details(self) -> bool:
        return model_memorial_sync.person_has_memorial_details(self)

    def clear_memorial_fields(self) -> None:
        model_memorial_sync.clear_person_memorial_fields(self)

    def sync_legacy_deceased_profile(self) -> None:
        model_memorial_sync.sync_person_legacy_deceased_profile(self)


class DeceasedProfile(TimestampedModel):
    person = models.OneToOneField(
        "imports.Person",
        on_delete=models.CASCADE,
        related_name="deceased_profile",
    )
    death_date_raw = models.CharField(max_length=64, blank=True)
    death_date = models.DateField(null=True, blank=True)
    death_date_parse_error = models.CharField(max_length=255, blank=True)
    kaimyo = models.CharField(max_length=255, blank=True)
    kaimyo_kana = models.CharField(max_length=255, blank=True)
    age_at_death_raw = models.CharField(max_length=32, blank=True)
    age_at_death = models.PositiveIntegerField(null=True, blank=True)
    age_unit = models.CharField(max_length=16, blank=True)
    legacy_hatsubon_flag = models.CharField(max_length=16, blank=True)
    hatsubon_flag = models.BooleanField(null=True, blank=True)
    memorial_notice_opt_out = models.BooleanField(null=True, blank=True)
    deceased_note = models.TextField(blank=True)
    memorial_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["person__person_uid"]

    def __str__(self) -> str:
        return self.kaimyo or self.person.name or self.person.person_uid

    def save(self, *args, **kwargs):  # type: ignore[override]
        return model_memorial_sync.save_deceased_profile(self, *args, **kwargs)

    def delete(self, *args, **kwargs):  # type: ignore[override]
        return model_memorial_sync.delete_deceased_profile(self, *args, **kwargs)


__all__ = [
    "DeceasedProfile",
    "Household",
    "HouseholdProfile",
    "Person",
]
