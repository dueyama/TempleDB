from __future__ import annotations

from datetime import time

from django import forms

from apps.core.services import tenant_policy as tenant_policy_services

from .forms_shared import GENDER_CHOICES, HALF_HOUR_TIME_CHOICES, _coerce_optional_time
from .forms_terminology import apply_deceased_field_labels
from .importer_parsing import _parse_legacy_date
from .kana import normalize_kana_storage
from .model_households import safe_display_head_name, safe_display_head_name_kana
from .models import (
    FAMILY_CATEGORY_CURRENT,
    FAMILY_CATEGORY_MEMORIAL,
    HOUSEHOLD_DELIVERY_CHOICES,
    HOUSEHOLD_DELIVERY_DISTRICT,
    LEDGER_CATEGORY_CHOICES,
    LEDGER_CATEGORY_CODES_BY_LABEL,
    District,
    Household,
)


class HouseholdEditForm(forms.ModelForm):
    head_person_name = forms.CharField(
        required=True,
        label="戸主氏名",
    )
    head_person_kana = forms.CharField(
        required=False,
        label="戸主フリガナ",
    )
    ledger_category = forms.ChoiceField(
        required=False,
        label="台帳区分",
        choices=LEDGER_CATEGORY_CHOICES,
        help_text="門徒 / 信徒 / その他 / 婦人会 を label で選びます。",
    )
    delivery_method = forms.ChoiceField(
        required=False,
        label="送付区分",
        choices=HOUSEHOLD_DELIVERY_CHOICES,
    )
    district_id = forms.ChoiceField(
        required=False,
        label="地区",
        choices=[("", "地区を選択")],
    )
    household_general_notice_opt_out = forms.BooleanField(
        required=False,
        label="案内要否",
        help_text="オンでこの家への案内全般を止めます。",
    )
    household_memorial_notice_opt_out = forms.BooleanField(
        required=False,
        label="年回要否",
        help_text="オンでこの家の年回連絡を止めます。故人ごとの年回案内不要より強く効きます。",
    )
    head_gender = forms.ChoiceField(
        required=False,
        label="戸主の性別",
        choices=GENDER_CHOICES,
        help_text="戸主に対応する person があれば、そちらの性別にも反映します。",
    )

    class Meta:
        model = Household
        fields = [
            "postal_code",
            "address_line1",
            "address_line2",
            "address_line3",
            "phone",
            "fax",
            "mobile",
            "email",
            "ledger_category",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(
        self,
        *args,
        districts: list[District] | None = None,
        initial_delivery_method: str = "",
        initial_district_id: str = "",
        initial_household_general_notice_opt_out: bool = False,
        initial_household_memorial_notice_opt_out: bool = False,
        initial_head_gender: str = "未決定",
        disable_head_identity_fields: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        resolved_head_name = (
            safe_display_head_name(self.instance)
            if getattr(self.instance, "pk", None)
            else (self.initial.get("head_person_name") or "")
        )
        resolved_head_name_kana = (
            safe_display_head_name_kana(self.instance)
            if getattr(self.instance, "pk", None)
            else (self.initial.get("head_person_kana") or "")
        )
        self.fields["head_person_name"].initial = resolved_head_name
        self.initial["head_person_name"] = resolved_head_name
        self.fields["head_person_kana"].initial = resolved_head_name_kana
        self.initial["head_person_kana"] = resolved_head_name_kana
        current_value = (self.instance.ledger_category or "").strip()
        if current_value in LEDGER_CATEGORY_CODES_BY_LABEL:
            current_value = LEDGER_CATEGORY_CODES_BY_LABEL[current_value]
        self.fields["ledger_category"].initial = current_value
        self.initial["ledger_category"] = current_value
        self.fields["district_id"].choices = [("", "地区を選択"), *[
            (str(district.pk), district.name) for district in (districts or [])
        ]]
        self.fields["delivery_method"].initial = initial_delivery_method
        self.initial["delivery_method"] = initial_delivery_method
        self.fields["district_id"].initial = initial_district_id
        self.initial["district_id"] = initial_district_id
        self.fields["household_general_notice_opt_out"].initial = bool(
            initial_household_general_notice_opt_out
        )
        self.initial["household_general_notice_opt_out"] = bool(
            initial_household_general_notice_opt_out
        )
        self.fields["household_memorial_notice_opt_out"].initial = bool(
            initial_household_memorial_notice_opt_out
        )
        self.initial["household_memorial_notice_opt_out"] = bool(
            initial_household_memorial_notice_opt_out
        )
        self.fields["head_gender"].initial = initial_head_gender or "未決定"
        self.initial["head_gender"] = initial_head_gender or "未決定"
        head_person = getattr(self.instance, "head_person", None)
        if head_person is not None and head_person.kana_is_auto_generated:
            self.fields["head_person_kana"].help_text = (
                "この戸主かなは自動補完です。手修正すると自動フラグは外れます。"
            )
        if disable_head_identity_fields:
            for field_name in ("head_person_name", "head_person_kana", "head_gender"):
                self.fields[field_name].disabled = True
            self.fields["head_person_name"].help_text = "仮戸主のため、この画面では変更できません。"
            self.fields["head_person_kana"].help_text = "仮戸主のため、この画面では変更できません。"
            self.fields["head_gender"].help_text = "仮戸主のため、この画面では変更できません。"
        self.order_fields(
            [
                "head_person_name",
                "head_person_kana",
                "head_gender",
                "postal_code",
                "address_line1",
                "address_line2",
                "address_line3",
                "phone",
                "fax",
                "mobile",
                "email",
                "delivery_method",
                "district_id",
                "household_general_notice_opt_out",
                "household_memorial_notice_opt_out",
                "ledger_category",
                "notes",
            ]
        )

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data["head_person_name"] = (cleaned_data.get("head_person_name") or "").strip()
        cleaned_data["head_person_kana"] = normalize_kana_storage(
            (cleaned_data.get("head_person_kana") or "").strip()
        )
        delivery_method = (cleaned_data.get("delivery_method") or "").strip()
        district_id = (cleaned_data.get("district_id") or "").strip()
        if delivery_method == HOUSEHOLD_DELIVERY_DISTRICT and not district_id:
            self.add_error("district_id", "地区所属を選ぶ場合は、地区も選択してください。")
        return cleaned_data

    def save(self, commit: bool = True) -> Household:
        household = super().save(commit=False)
        ledger_category = (self.cleaned_data.get("ledger_category") or "").strip()
        household.ledger_category = ledger_category
        if commit:
            household.save()
        return household


class NewHouseholdForm(forms.Form):
    head_name = forms.CharField(required=True, label="戸主氏名")
    head_name_kana = forms.CharField(required=False, label="戸主かな")
    head_gender = forms.ChoiceField(required=False, label="戸主の性別", choices=GENDER_CHOICES)
    postal_code = forms.CharField(required=False, label="〒")
    address_line1 = forms.CharField(required=False, label="住所1")
    address_line2 = forms.CharField(required=False, label="住所2")
    address_line3 = forms.CharField(required=False, label="住所3")
    phone = forms.CharField(required=False, label="電話")
    mobile = forms.CharField(required=False, label="携帯")
    email = forms.CharField(required=False, label="Email")
    ledger_category = forms.ChoiceField(
        required=False,
        label="台帳区分",
        choices=LEDGER_CATEGORY_CHOICES,
        help_text="門徒 / 信徒 / その他 / 婦人会 を label で選びます。",
    )
    notes = forms.CharField(
        required=False,
        label="家の備考",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["head_gender"].initial = self.initial.get("head_gender") or "未決定"

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data["head_name"] = (cleaned_data.get("head_name") or "").strip()
        cleaned_data["head_name_kana"] = normalize_kana_storage(
            (cleaned_data.get("head_name_kana") or "").strip()
        )
        gender = (cleaned_data.get("head_gender") or "").strip()
        cleaned_data["head_gender"] = gender if gender in {choice[0] for choice in GENDER_CHOICES} else "未決定"
        for field_name in (
            "postal_code",
            "address_line1",
            "address_line2",
            "address_line3",
            "phone",
            "mobile",
            "email",
            "ledger_category",
            "notes",
        ):
            cleaned_data[field_name] = (cleaned_data.get(field_name) or "").strip()
        return cleaned_data


class VirtualHeadReplacementForm(forms.Form):
    SUCCESSOR_MODE_CURRENT = "current"
    SUCCESSOR_MODE_MANUAL = "manual"
    successor_mode = forms.ChoiceField(
        required=False,
        label="設定方法",
        choices=[
            (SUCCESSOR_MODE_CURRENT, "現在帳から選ぶ"),
            (SUCCESSOR_MODE_MANUAL, "新しく入力する"),
        ],
        initial=SUCCESSOR_MODE_CURRENT,
    )
    successor_person_id = forms.ChoiceField(
        required=False,
        label="現在帳から選ぶ",
        choices=[("", "---------")],
    )
    manual_head_name = forms.CharField(
        required=False,
        label="新戸主名",
    )
    manual_head_name_kana = forms.CharField(
        required=False,
        label="新戸主かな",
    )

    def __init__(
        self,
        *args,
        successor_choices: list[tuple[str, str]] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["successor_person_id"].choices = [("", "---------"), *(successor_choices or [])]
        if not successor_choices:
            self.initial.setdefault("successor_mode", self.SUCCESSOR_MODE_MANUAL)
            self.fields["successor_person_id"].help_text = "現在帳に候補がいないため、新しく入力してください。"

    def clean(self):
        cleaned_data = super().clean()
        mode = (cleaned_data.get("successor_mode") or self.initial.get("successor_mode") or self.SUCCESSOR_MODE_CURRENT).strip()
        cleaned_data["successor_mode"] = mode
        successor_person_id = (cleaned_data.get("successor_person_id") or "").strip()
        manual_head_name = (cleaned_data.get("manual_head_name") or "").strip()
        cleaned_data["manual_head_name"] = manual_head_name
        cleaned_data["manual_head_name_kana"] = normalize_kana_storage(
            (cleaned_data.get("manual_head_name_kana") or "").strip()
        )
        if mode == self.SUCCESSOR_MODE_CURRENT and not successor_person_id:
            self.add_error("successor_person_id", "現在帳から選ぶ場合は対象を選んでください。")
        if mode == self.SUCCESSOR_MODE_MANUAL and not manual_head_name:
            self.add_error("manual_head_name", "新戸主名を入力してください。")
        return cleaned_data


class HouseholdHeadTransitionForm(forms.Form):
    REGISTRATION_MODE_FUNERAL = "funeral"
    REGISTRATION_MODE_HISTORICAL = "historical"
    SUCCESSOR_MODE_KEEP = "keep"
    SUCCESSOR_MODE_CURRENT = "current"
    SUCCESSOR_MODE_MANUAL = "manual"

    registration_mode = forms.ChoiceField(
        required=False,
        label="登録方法",
        choices=[
            (REGISTRATION_MODE_FUNERAL, "往生として登録（葬儀も作る）"),
            (REGISTRATION_MODE_HISTORICAL, "昔の故人として登録（葬儀イベントは作らない）"),
        ],
        initial=REGISTRATION_MODE_FUNERAL,
    )
    death_date_input = forms.CharField(
        required=False,
        label="命日",
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date", "autocomplete": "off"},
        ),
    )
    kaimyo = forms.CharField(required=False)
    kaimyo_kana = forms.CharField(required=False)
    age_at_death = forms.IntegerField(required=False, min_value=0, label="享年")
    age_unit = forms.CharField(required=False, label="享年単位")
    relationship_label = forms.CharField(required=False, label="続柄")
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
            attrs={"type": "date", "autocomplete": "off"},
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
    successor_mode = forms.ChoiceField(
        required=False,
        label="次の戸主",
        choices=[
            (SUCCESSOR_MODE_KEEP, "いまの戸主名のままにする（仮戸主扱い）"),
            (SUCCESSOR_MODE_CURRENT, "現在帳から選ぶ"),
            (SUCCESSOR_MODE_MANUAL, "新しく入力する"),
        ],
        initial=SUCCESSOR_MODE_KEEP,
    )
    successor_person_id = forms.ChoiceField(
        required=False,
        label="現在帳から選ぶ",
        choices=[("", "---------")],
    )
    manual_head_name = forms.CharField(
        required=False,
        label="新戸主名",
    )
    manual_head_name_kana = forms.CharField(
        required=False,
        label="新戸主かな",
    )

    def __init__(
        self,
        *args,
        target_category: str,
        successor_choices: list[tuple[str, str]] | None = None,
        include_successor_fields: bool = True,
        relationship_initial: str = "",
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        apply_deceased_field_labels(self, tenant_policy_services=tenant_policy_services)
        self.target_category = target_category
        self.include_successor_fields = include_successor_fields
        self.fields["successor_person_id"].choices = [("", "---------"), *(successor_choices or [])]
        self.fields["age_unit"].initial = self.initial.get("age_unit") or "歳"
        self.fields["funeral_scheduled_time"].initial = (
            self.initial.get("funeral_scheduled_time") or "10:00"
        )
        if relationship_initial and not self.initial.get("relationship_label"):
            self.fields["relationship_label"].initial = relationship_initial
        if target_category == FAMILY_CATEGORY_CURRENT:
            self.fields["registration_mode"].widget = forms.HiddenInput()
            self.fields["death_date_input"].widget = forms.HiddenInput()
            self.fields["kaimyo"].widget = forms.HiddenInput()
            self.fields["kaimyo_kana"].widget = forms.HiddenInput()
            self.fields["age_at_death"].widget = forms.HiddenInput()
            self.fields["age_unit"].widget = forms.HiddenInput()
            self.fields["relationship_label"].widget = forms.HiddenInput()
            self.fields["deceased_note"].widget = forms.HiddenInput()
            self.fields["funeral_scheduled_date_input"].widget = forms.HiddenInput()
            self.fields["funeral_scheduled_time"].widget = forms.HiddenInput()
            self.fields["funeral_location"].widget = forms.HiddenInput()
            self.fields["successor_mode"].widget = forms.HiddenInput()
            self.fields["successor_person_id"].widget = forms.HiddenInput()
            self.fields["manual_head_name"].widget = forms.HiddenInput()
            self.fields["manual_head_name_kana"].widget = forms.HiddenInput()
        elif not include_successor_fields:
            self.fields["successor_mode"].widget = forms.HiddenInput()
            self.fields["successor_person_id"].widget = forms.HiddenInput()
            self.fields["manual_head_name"].widget = forms.HiddenInput()
            self.fields["manual_head_name_kana"].widget = forms.HiddenInput()

    def clean(self):
        cleaned_data = super().clean()
        if self.target_category != FAMILY_CATEGORY_MEMORIAL:
            return cleaned_data
        registration_mode = (
            cleaned_data.get("registration_mode") or self.REGISTRATION_MODE_FUNERAL
        ).strip()
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
        if registration_mode == self.REGISTRATION_MODE_FUNERAL and cleaned_data.get("funeral_scheduled_time") is None:
            cleaned_data["funeral_scheduled_time"] = time(hour=10, minute=0)
        cleaned_data["kaimyo_kana"] = normalize_kana_storage(
            (cleaned_data.get("kaimyo_kana") or "").strip()
        )
        mode = (cleaned_data.get("successor_mode") or self.SUCCESSOR_MODE_KEEP).strip()
        successor_person_id = (cleaned_data.get("successor_person_id") or "").strip()
        manual_head_name = (cleaned_data.get("manual_head_name") or "").strip()
        cleaned_data["manual_head_name_kana"] = normalize_kana_storage(
            (cleaned_data.get("manual_head_name_kana") or "").strip()
        )
        if self.include_successor_fields and mode == self.SUCCESSOR_MODE_CURRENT and not successor_person_id:
            self.add_error("successor_person_id", "現在帳から選ぶ場合は対象を選んでください。")
        if self.include_successor_fields and mode == self.SUCCESSOR_MODE_MANUAL and not manual_head_name:
            self.add_error("manual_head_name", "新戸主名を入力してください。")
        return cleaned_data
