from __future__ import annotations

from django import forms
from django.forms import inlineformset_factory

from .forms_shared import PAYMENT_CATEGORY_CHOICES
from .models import AnnualMembershipFeeSetting, Household, OfferingPayment, Person, ServiceSchedule


class OfferingPaymentForm(forms.ModelForm):
    class Meta:
        model = OfferingPayment
        fields = [
            "received_on",
            "payment_category",
            "amount",
            "payment_method",
            "received_by",
            "notes",
        ]
        widgets = {
            "received_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["received_on"].label = "入金日"
        self.fields["payment_category"].label = "区分"
        self.fields["payment_category"].choices = PAYMENT_CATEGORY_CHOICES
        self.fields["amount"].label = "金額"
        self.fields["payment_method"].label = "受領方法"
        self.fields["received_by"].label = "受領者"
        self.fields["notes"].label = "メモ"
        self.fields["payment_method"].required = False
        self.fields["payment_method"].initial = (
            self.instance.payment_method
            if getattr(self.instance, "pk", None)
            else OfferingPayment.Method.CASH
        )
        if not getattr(self.instance, "pk", None):
            self.fields["received_on"].initial = self.initial.get("received_on") or ""


class StandaloneOfferingPaymentForm(OfferingPaymentForm):
    person = forms.ModelChoiceField(
        queryset=Person.objects.none(),
        required=False,
        empty_label="家全体",
        label="対象者",
    )

    class Meta(OfferingPaymentForm.Meta):
        fields = [
            "received_on",
            "payment_category",
            "amount",
            "person",
            "payment_method",
            "received_by",
            "notes",
        ]

    def __init__(
        self,
        *args,
        household: Household,
        person_queryset=None,
        **kwargs,
    ) -> None:
        self.household = household
        super().__init__(*args, **kwargs)
        queryset = person_queryset
        if queryset is None:
            queryset = Person.objects.filter(
                batch=household.batch,
                household=household,
                deleted_at__isnull=True,
            ).order_by("family_category", "person_uid")
        self.fields["person"].queryset = queryset
        self.fields["person"].help_text = "家全体の入金なら空欄のままにします。"

    def clean_person(self):
        person = self.cleaned_data.get("person")
        if person is None:
            return None
        if person.household_id != self.household.id:
            raise forms.ValidationError("この家に属する人だけを選択できます。")
        return person


OfferingPaymentFormSet = inlineformset_factory(
    ServiceSchedule,
    OfferingPayment,
    form=OfferingPaymentForm,
    extra=3,
    can_delete=True,
)


class AnnualMembershipFeeSettingForm(forms.ModelForm):
    class Meta:
        model = AnnualMembershipFeeSetting
        fields = ["default_amount", "note"]
        widgets = {
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["default_amount"].label = "今年の既定額"
        self.fields["note"].label = "メモ"


class AnnualMembershipFeeEntryForm(forms.Form):
    paid = forms.BooleanField(required=False, label="支払済み")
    received_on = forms.DateField(
        required=False,
        label="入金日",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    is_exception = forms.BooleanField(required=False, label="例外")
    amount_override = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=0,
        min_value=0,
        label="例外金額",
    )
    note = forms.CharField(
        required=False,
        label="メモ",
        widget=forms.TextInput(attrs={"placeholder": "必要時のみ"}),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["paid"].widget.attrs["data-fee-paid"] = "1"
        self.fields["is_exception"].widget.attrs["data-fee-exception-toggle"] = "1"
        self.fields["amount_override"].widget.attrs["data-fee-exception-amount"] = "1"

    def clean(self):
        cleaned_data = super().clean()
        paid = bool(cleaned_data.get("paid"))
        is_exception = bool(cleaned_data.get("is_exception"))
        amount_override = cleaned_data.get("amount_override")
        if is_exception and amount_override in {None, ""}:
            self.add_error("amount_override", "例外を使う場合は金額を入力してください。")
        if not paid:
            cleaned_data["received_on"] = None
            cleaned_data["is_exception"] = False
            cleaned_data["amount_override"] = None
            cleaned_data["note"] = (cleaned_data.get("note") or "").strip()
        return cleaned_data
