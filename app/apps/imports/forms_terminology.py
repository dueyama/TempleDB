from __future__ import annotations

from django import forms

from apps.core.services import tenant_policy as tenant_policy_services


def apply_deceased_field_labels(
    form: forms.BaseForm,
    *,
    tenant_policy_services=tenant_policy_services,
) -> None:
    labels = tenant_policy_services.deceased_field_labels()
    if "kaimyo" in form.fields:
        form.fields["kaimyo"].label = labels["kaimyo"]
    if "kaimyo_kana" in form.fields:
        form.fields["kaimyo_kana"].label = labels["kaimyo_kana"]


__all__ = ["apply_deceased_field_labels"]
