from __future__ import annotations

from django.db import models
from django.utils import timezone

FAMILY_CATEGORY_CURRENT = "0"
FAMILY_CATEGORY_MEMORIAL = "1"
FAMILY_CATEGORY_CHOICES = (
    ("", "未設定"),
    (FAMILY_CATEGORY_CURRENT, "現在帳"),
    (FAMILY_CATEGORY_MEMORIAL, "過去帳"),
)
FAMILY_CATEGORY_LABELS = dict(FAMILY_CATEGORY_CHOICES)
LEDGER_CATEGORY_WOMENS_ASSOCIATION = "4"
LEDGER_CATEGORY_CHOICES = (
    ("", "未設定"),
    ("1", "門徒"),
    ("2", "信徒"),
    ("3", "その他"),
    (LEDGER_CATEGORY_WOMENS_ASSOCIATION, "婦人会"),
)
LEDGER_CATEGORY_LABELS = dict(LEDGER_CATEGORY_CHOICES)
LEDGER_CATEGORY_CODES_BY_LABEL = {
    label: code for code, label in LEDGER_CATEGORY_CHOICES if code
}
HOUSEHOLD_DELIVERY_DISTRICT = "district"
HOUSEHOLD_DELIVERY_POSTAL = "postal"
HOUSEHOLD_DELIVERY_NONE = "none"
HOUSEHOLD_DELIVERY_CHOICES = (
    ("", "未設定"),
    (HOUSEHOLD_DELIVERY_DISTRICT, "地区所属"),
    (HOUSEHOLD_DELIVERY_POSTAL, "郵送"),
    (HOUSEHOLD_DELIVERY_NONE, "送付しない"),
)
HOUSEHOLD_DELIVERY_LABELS = dict(HOUSEHOLD_DELIVERY_CHOICES)


class HouseholdHeadResolutionError(RuntimeError):
    pass


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteMixin(models.Model):
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.CharField(max_length=100, blank=True)
    deletion_note = models.TextField(blank=True)

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def mark_deleted(self, *, editor_label: str = "", note: str = "") -> None:
        self.deleted_at = timezone.now()
        self.deleted_by = (editor_label or "").strip()
        self.deletion_note = (note or "").strip()

    def restore_deleted(self) -> None:
        self.deleted_at = None
        self.deleted_by = ""
        self.deletion_note = ""


__all__ = [
    "FAMILY_CATEGORY_CHOICES",
    "FAMILY_CATEGORY_CURRENT",
    "FAMILY_CATEGORY_LABELS",
    "FAMILY_CATEGORY_MEMORIAL",
    "HOUSEHOLD_DELIVERY_CHOICES",
    "HOUSEHOLD_DELIVERY_DISTRICT",
    "HOUSEHOLD_DELIVERY_LABELS",
    "HOUSEHOLD_DELIVERY_NONE",
    "HOUSEHOLD_DELIVERY_POSTAL",
    "HouseholdHeadResolutionError",
    "LEDGER_CATEGORY_CHOICES",
    "LEDGER_CATEGORY_CODES_BY_LABEL",
    "LEDGER_CATEGORY_LABELS",
    "LEDGER_CATEGORY_WOMENS_ASSOCIATION",
    "SoftDeleteMixin",
    "TimestampedModel",
]
