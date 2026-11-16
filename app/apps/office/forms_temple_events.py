from django import forms
from django.forms import inlineformset_factory

from apps.imports.forms_accounting import OfferingPaymentForm
from apps.imports.models import Household, OfferingPayment, ServiceSchedule


class HouseholdChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.display_head_name()}（{obj.household_uid}）"


class TempleEventForm(forms.ModelForm):
    household = HouseholdChoiceField(
        queryset=Household.objects.none(),
        required=False,
        label="関連する家",
        empty_label="家に紐づけない",
    )
    version = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = ServiceSchedule
        fields = [
            "service_label",
            "scheduled_date",
            "scheduled_time",
            "location",
            "subject_name",
            "household",
            "status",
            "completed_on",
            "notes",
        ]
        labels = {
            "service_label": "予定の名前",
            "scheduled_date": "日付",
            "scheduled_time": "時刻",
            "location": "場所",
            "subject_name": "相手先・来訪者",
            "status": "状態",
            "completed_on": "完了日",
            "notes": "メモ",
        }
        widgets = {
            "scheduled_date": forms.DateInput(attrs={"type": "date"}),
            "completed_on": forms.DateInput(attrs={"type": "date"}),
            "scheduled_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, households, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["household"].queryset = households
        self.fields[
            "household"
        ].help_text = "任意です。予定の関連先であり、納入者の家は入金ごとに指定します。"
        self.fields["scheduled_date"].required = True
        self.fields["status"].choices = [
            choice
            for choice in ServiceSchedule.Status.choices
            if choice[0] != ServiceSchedule.Status.CANDIDATE
        ]
        if self.instance.pk:
            self.fields["version"].initial = self.instance.updated_at.isoformat()

    def clean(self):
        data = super().clean()
        if data.get("status") == ServiceSchedule.Status.COMPLETED and not data.get("completed_on"):
            data["completed_on"] = data.get("scheduled_date")
        elif data.get("status") != ServiceSchedule.Status.COMPLETED:
            data["completed_on"] = None
        return data


class TempleEventPaymentForm(OfferingPaymentForm):
    household = HouseholdChoiceField(
        queryset=Household.objects.none(),
        required=False,
        label="納入者の家",
        empty_label="家に紐づけない",
    )

    class Meta(OfferingPaymentForm.Meta):
        fields = ["payer_name", "household", *OfferingPaymentForm.Meta.fields]
        labels = {"payer_name": "納入者名"}

    def __init__(self, *args, households, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["household"].queryset = households
        self.fields[
            "payer_name"
        ].help_text = "家の登録は不要です。名前と家の両方が空欄なら匿名として表示します。"
        self.fields["amount"].min_value = 0
        self.fields["amount"].widget.attrs["min"] = "0"

    def clean_amount(self):
        value = self.cleaned_data["amount"]
        if value < 0:
            raise forms.ValidationError("金額は0円以上で入力してください。")
        return value

    def has_changed(self):
        # Browser-submitted date/category/method defaults are not a receipt.
        if not self.instance.pk and self.is_bound:
            meaningful_fields = ("amount", "payer_name", "household", "received_by", "notes", "id")
            if not any(
                str(self.data.get(self.add_prefix(key), "") or "").strip()
                for key in meaningful_fields
            ):
                return False
        return super().has_changed()


TempleEventPaymentFormSet = inlineformset_factory(
    ServiceSchedule,
    OfferingPayment,
    form=TempleEventPaymentForm,
    extra=1,
    can_delete=True,
    max_num=1000,
    validate_max=True,
)
