from django import forms
from django.utils import timezone

from apps.imports.models import OfferingPayment


class HomeServiceCompletionForm(forms.Form):
    state = forms.CharField(widget=forms.HiddenInput, max_length=16384)
    amount = forms.DecimalField(
        label="お布施（円）", required=False, max_digits=12, decimal_places=0, min_value=0,
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "placeholder": "空欄なら完了のみ"}),
    )
    completed_on = forms.DateField(label="実施・入金日", widget=forms.DateInput(attrs={"type": "date"}))
    payment_method = forms.ChoiceField(label="受領方法", choices=OfferingPayment.Method.choices)

    def clean_completed_on(self):
        value = self.cleaned_data["completed_on"]
        if value > timezone.localdate():
            raise forms.ValidationError("実施・入金日は今日以前の日付を指定してください。")
        return value
