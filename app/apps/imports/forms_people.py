from __future__ import annotations

from datetime import time

from django import forms

from apps.core.services import tenant_policy as tenant_policy_services

from .forms_households import HouseholdHeadTransitionForm
from .forms_shared import (
    GENDER_CHOICES,
    HALF_HOUR_TIME_CHOICES,
    NULLABLE_BOOL_CHOICES,
    _bool_to_choice,
    _bool_to_legacy,
    _coerce_nullable_bool,
    _coerce_optional_time,
    _person_is_deceased_initial,
)
from .forms_terminology import apply_deceased_field_labels
from .importer_parsing import _parse_legacy_date
from .kana import normalize_kana_storage
from .models import (
    FAMILY_CATEGORY_CHOICES,
    FAMILY_CATEGORY_CURRENT,
    FAMILY_CATEGORY_MEMORIAL,
    Person,
)


def _apply_role_labels(form: forms.BaseForm) -> None:
    labels = tenant_policy_services.role_labels()
    if "is_district_officer" in form.fields:
        form.fields["is_district_officer"].label = labels["district_officer"]
    if "is_responsible_officer" in form.fields:
        form.fields["is_responsible_officer"].label = labels["responsible_officer"]
    if "is_monto_sodai" in form.fields:
        form.fields["is_monto_sodai"].label = labels["monto_sodai"]


class NewMemorialRegistrationForm(forms.Form):
    registration_mode = forms.ChoiceField(
        required=False,
        label="登録方法",
        choices=[
            (HouseholdHeadTransitionForm.REGISTRATION_MODE_FUNERAL, "往生として登録（葬儀も作る）"),
            (HouseholdHeadTransitionForm.REGISTRATION_MODE_HISTORICAL, "昔の故人として登録（葬儀イベントは作らない）"),
        ],
        initial=HouseholdHeadTransitionForm.REGISTRATION_MODE_FUNERAL,
    )
    name = forms.CharField(required=True, label="氏名")
    kana = forms.CharField(required=False, label="かな")
    gender = forms.ChoiceField(required=False, label="性別", choices=GENDER_CHOICES)
    birth_date_input = forms.CharField(
        required=False,
        label="生年月日",
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "text", "inputmode": "numeric", "autocomplete": "off"},
        ),
    )
    relationship_label = forms.CharField(required=False, label="続柄")
    death_date_input = forms.CharField(
        required=False,
        label="命日",
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "text", "inputmode": "numeric", "autocomplete": "off"},
        ),
    )
    kaimyo = forms.CharField(required=False)
    kaimyo_kana = forms.CharField(required=False)
    age_at_death = forms.IntegerField(required=False, min_value=0, label="享年")
    age_unit = forms.CharField(required=False, label="享年単位")
    deceased_note = forms.CharField(
        required=False,
        label="故人備考",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    funeral_scheduled_date_input = forms.CharField(
        required=False,
        label="葬儀日",
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "text", "inputmode": "numeric", "autocomplete": "off"},
        ),
    )
    funeral_scheduled_time = forms.TypedChoiceField(
        required=False,
        label="葬儀時刻",
        choices=HALF_HOUR_TIME_CHOICES,
        coerce=_coerce_optional_time,
        empty_value=None,
        initial="10:00",
    )
    funeral_location = forms.CharField(required=False, label="葬儀場所")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        apply_deceased_field_labels(self, tenant_policy_services=tenant_policy_services)
        self.fields["gender"].initial = self.initial.get("gender") or "未決定"
        self.fields["age_unit"].initial = self.initial.get("age_unit") or "歳"
        self.fields["funeral_scheduled_time"].initial = (
            self.initial.get("funeral_scheduled_time") or "10:00"
        )

    def clean(self):
        cleaned_data = super().clean()
        birth_input = (cleaned_data.get("birth_date_input") or "").strip()
        parsed_birth = _parse_legacy_date(birth_input)
        if birth_input and parsed_birth.value is None:
            self.add_error(
                "birth_date_input",
                "日付を解釈できません。YYYY-MM-DD または 昭和/平成/令和の形式で入力してください。",
            )
        cleaned_data["birth_date_input"] = parsed_birth.value

        death_input = (cleaned_data.get("death_date_input") or "").strip()
        if not death_input:
            self.add_error("death_date_input", "命日を入力してください。")
        parsed_death = _parse_legacy_date(death_input)
        if death_input and parsed_death.value is None:
            self.add_error(
                "death_date_input",
                "日付を解釈できません。YYYY-MM-DD または 昭和/平成/令和の形式で入力してください。",
            )
        cleaned_data["death_date_input"] = parsed_death.value

        funeral_input = (cleaned_data.get("funeral_scheduled_date_input") or "").strip()
        parsed_funeral = _parse_legacy_date(funeral_input)
        if funeral_input and parsed_funeral.value is None:
            self.add_error(
                "funeral_scheduled_date_input",
                "日付を解釈できません。YYYY-MM-DD または 昭和/平成/令和の形式で入力してください。",
            )
        cleaned_data["funeral_scheduled_date_input"] = parsed_funeral.value
        if (
            (cleaned_data.get("registration_mode") or HouseholdHeadTransitionForm.REGISTRATION_MODE_FUNERAL)
            == HouseholdHeadTransitionForm.REGISTRATION_MODE_FUNERAL
            and cleaned_data.get("funeral_scheduled_time") is None
        ):
            cleaned_data["funeral_scheduled_time"] = time(hour=10, minute=0)
        cleaned_data["name"] = (cleaned_data.get("name") or "").strip()
        cleaned_data["kana"] = normalize_kana_storage((cleaned_data.get("kana") or "").strip())
        cleaned_data["kaimyo_kana"] = normalize_kana_storage(
            (cleaned_data.get("kaimyo_kana") or "").strip()
        )
        cleaned_data["relationship_label"] = (cleaned_data.get("relationship_label") or "").strip()
        return cleaned_data


class NewCurrentPersonForm(forms.Form):
    name = forms.CharField(required=True, label="氏名")
    kana = forms.CharField(required=False, label="かな")
    gender = forms.ChoiceField(required=False, label="性別", choices=GENDER_CHOICES)
    birth_date_input = forms.CharField(
        required=False,
        label="生年月日",
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "text", "inputmode": "numeric", "autocomplete": "off"},
        ),
    )
    relationship_label = forms.CharField(required=False, label="続柄")
    person_note = forms.CharField(
        required=False,
        label="個人備考",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["gender"].initial = self.initial.get("gender") or "未決定"

    def clean(self):
        cleaned_data = super().clean()
        birth_input = (cleaned_data.get("birth_date_input") or "").strip()
        parsed_birth = _parse_legacy_date(birth_input)
        if birth_input and parsed_birth.value is None:
            self.add_error(
                "birth_date_input",
                "日付を解釈できません。YYYY-MM-DD または 昭和/平成/令和の形式で入力してください。",
            )
        cleaned_data["birth_date_input"] = parsed_birth.value
        cleaned_data["name"] = (cleaned_data.get("name") or "").strip()
        cleaned_data["kana"] = normalize_kana_storage((cleaned_data.get("kana") or "").strip())
        cleaned_data["relationship_label"] = (cleaned_data.get("relationship_label") or "").strip()
        return cleaned_data


class PersonEditForm(forms.ModelForm):
    birth_date_input = forms.CharField(
        required=False,
        label="生年月日",
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "text", "inputmode": "numeric", "autocomplete": "off"},
        ),
    )
    death_date_input = forms.CharField(
        required=False,
        label="命日",
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "text", "inputmode": "numeric", "autocomplete": "off"},
        ),
    )
    kaimyo = forms.CharField(required=False)
    kaimyo_kana = forms.CharField(required=False)
    family_category = forms.ChoiceField(
        required=False,
        label="家族区分",
        choices=FAMILY_CATEGORY_CHOICES,
        help_text="現在帳/過去帳の扱いはこの区分を正として扱います。",
    )
    relationship_label = forms.CharField(
        required=False,
        label="続柄",
        help_text="必要なら自由入力できます。右の候補から選ぶと、この欄へ入ります。",
    )
    relationship_choice = forms.ChoiceField(
        required=False,
        label="候補から入力",
        choices=[("", "---------")],
    )
    gender = forms.ChoiceField(required=False, label="性別", choices=GENDER_CHOICES)
    is_district_officer = forms.BooleanField(required=False, label="地区役員")
    is_responsible_officer = forms.BooleanField(required=False, label="責任役員")
    is_monto_sodai = forms.BooleanField(required=False, label="門徒総代")
    age_at_death = forms.IntegerField(required=False, min_value=0, label="享年")
    age_unit = forms.CharField(required=False, label="享年単位")
    hatsubon_flag = forms.TypedChoiceField(
        required=False,
        label="初盆",
        choices=NULLABLE_BOOL_CHOICES,
        coerce=_coerce_nullable_bool,
        empty_value=None,
    )
    memorial_notice_opt_out = forms.BooleanField(
        required=False,
        label="年回案内不要",
        help_text="オンにすると、この故人は翌年回忌案内などの案内対象から外します。",
    )
    deceased_note = forms.CharField(
        required=False,
        label="故人備考",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = Person
        fields = [
            "name",
            "kana",
            "relationship_label",
            "family_category",
            "gender",
            "is_district_officer",
            "is_responsible_officer",
            "is_monto_sodai",
            "is_deceased",
            "person_note",
        ]
        widgets = {
            "person_note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(
        self,
        *args,
        relationship_choices: list[tuple[str, str]] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        apply_deceased_field_labels(self, tenant_policy_services=tenant_policy_services)
        _apply_role_labels(self)
        self._original_kana = normalize_kana_storage(self.instance.kana)
        if relationship_choices:
            self.fields["relationship_choice"].choices = relationship_choices
        self.fields["gender"].initial = self.instance.gender or "未決定"
        self.initial["gender"] = self.instance.gender or "未決定"
        self.fields["is_district_officer"].initial = bool(self.instance.is_district_officer)
        self.fields["is_responsible_officer"].initial = bool(self.instance.is_responsible_officer)
        self.fields["is_monto_sodai"].initial = bool(self.instance.is_monto_sodai)
        self.fields["birth_date_input"].initial = self.instance.birth_date.isoformat() if self.instance.birth_date else ""
        self.fields["is_deceased"].initial = _person_is_deceased_initial(self.instance)
        self.fields["death_date_input"].initial = (
            self.instance.death_date.isoformat() if self.instance.death_date else ""
        )
        self.fields["kaimyo"].initial = self.instance.kaimyo
        self.fields["kaimyo_kana"].initial = self.instance.kaimyo_kana
        self.fields["age_at_death"].initial = self.instance.age_at_death
        self.fields["age_unit"].initial = self.instance.age_unit or "歳"
        self.fields["hatsubon_flag"].initial = _bool_to_choice(self.instance.hatsubon_flag)
        self.fields["memorial_notice_opt_out"].initial = bool(self.instance.memorial_notice_opt_out)
        self.fields["deceased_note"].initial = self.instance.deceased_note
        if self.instance.kana_is_auto_generated:
            self.fields["kana"].help_text = "このかなは自動補完です。手修正すると自動フラグは外れます。"

    def clean(self):
        cleaned_data = super().clean()
        birth_input = (cleaned_data.get("birth_date_input") or "").strip()
        death_input = (cleaned_data.get("death_date_input") or "").strip()

        parsed_birth = _parse_legacy_date(birth_input)
        if birth_input and parsed_birth.value is None:
            self.add_error(
                "birth_date_input",
                "日付を解釈できません。YYYY-MM-DD または 昭和/平成/令和の形式で入力してください。",
            )
        cleaned_data["birth_date_input"] = parsed_birth.value

        parsed_death = _parse_legacy_date(death_input)
        if death_input and parsed_death.value is None:
            self.add_error(
                "death_date_input",
                "日付を解釈できません。YYYY-MM-DD または 昭和/平成/令和の形式で入力してください。",
            )
        cleaned_data["death_date_input"] = parsed_death.value
        cleaned_data["kana"] = normalize_kana_storage((cleaned_data.get("kana") or "").strip())
        cleaned_data["kaimyo_kana"] = normalize_kana_storage(
            (cleaned_data.get("kaimyo_kana") or "").strip()
        )
        return cleaned_data

    def save(self, commit: bool = True) -> Person:
        person = super().save(commit=False)
        person.kana_is_auto_generated = bool(
            person.kana_is_auto_generated and person.kana == self._original_kana
        )
        person.relationship_label = (self.cleaned_data.get("relationship_label") or "").strip()
        birth_date = self.cleaned_data["birth_date_input"]
        death_date = self.cleaned_data["death_date_input"]
        family_category = self.cleaned_data["family_category"]
        person.is_district_officer = bool(self.cleaned_data["is_district_officer"])
        person.is_responsible_officer = bool(self.cleaned_data["is_responsible_officer"])
        person.is_monto_sodai = bool(self.cleaned_data["is_monto_sodai"])
        profile_fields_present = any(
            (
                death_date,
                self.cleaned_data["kaimyo"],
                self.cleaned_data["kaimyo_kana"],
                self.cleaned_data["age_at_death"],
                self.cleaned_data["deceased_note"],
                self.cleaned_data["hatsubon_flag"] is not None,
                self.cleaned_data["memorial_notice_opt_out"],
            )
        )
        if family_category == FAMILY_CATEGORY_MEMORIAL:
            person.is_deceased = True
        elif family_category == FAMILY_CATEGORY_CURRENT:
            person.is_deceased = False
        else:
            death_evidence_present = any(
                (
                    death_date,
                    self.cleaned_data["age_at_death"],
                    self.cleaned_data["deceased_note"],
                    self.cleaned_data["hatsubon_flag"] is True,
                )
            )
            person.is_deceased = bool(self.cleaned_data["is_deceased"] or death_evidence_present)
        person.birth_date = birth_date
        person.birth_date_raw = birth_date.isoformat() if birth_date else ""
        person.birth_date_parse_error = ""
        if not person.is_deceased and not profile_fields_present:
            person.clear_memorial_fields()
        else:
            age_at_death = self.cleaned_data["age_at_death"]
            person.death_date = death_date
            person.death_date_raw = death_date.isoformat() if death_date else ""
            person.death_date_parse_error = ""
            person.kaimyo = self.cleaned_data["kaimyo"]
            person.kaimyo_kana = self.cleaned_data["kaimyo_kana"]
            person.age_at_death = age_at_death
            person.age_at_death_raw = str(age_at_death) if age_at_death is not None else ""
            person.age_unit = self.cleaned_data["age_unit"] or "歳"
            person.hatsubon_flag = self.cleaned_data["hatsubon_flag"]
            person.legacy_hatsubon_flag = _bool_to_legacy(person.hatsubon_flag)
            person.memorial_notice_opt_out = bool(self.cleaned_data["memorial_notice_opt_out"])
            person.deceased_note = self.cleaned_data["deceased_note"]
        if commit:
            person.save()
            person.sync_legacy_deceased_profile()
        return person
