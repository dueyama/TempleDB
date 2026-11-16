from __future__ import annotations

from datetime import date

from django import forms

from apps.core.services import tenant_policy

from .forms_shared import HALF_HOUR_TIME_CHOICES, _coerce_optional_time
from .models import ServiceSchedule


def _service_schedule_category_policy_fallback() -> list[dict]:
    return [
        {"code": value, "label": label, "seq": index}
        for index, (value, label) in enumerate(ServiceSchedule.Category.choices, start=1)
    ]


def _service_schedule_category_choices() -> list[tuple[str, str]]:
    return tenant_policy.service_schedule_category_choices(
        fallback_categories=_service_schedule_category_policy_fallback()
    )


def _is_generic_other_event(category: str | None, service_label: str | None = None) -> bool:
    normalized_category = str(category or "").strip()
    normalized_label = str(service_label or "").strip()
    return normalized_category in {
        ServiceSchedule.Category.BON,
        ServiceSchedule.Category.OTOKOSHI,
    } or (
        normalized_category == ServiceSchedule.Category.OTHER and normalized_label != "葬儀"
    )


def _household_only_event_label(category: str | None) -> str:
    normalized_category = str(category or "").strip()
    if normalized_category == ServiceSchedule.Category.BON:
        return ServiceSchedule.Category.BON.label
    if normalized_category == ServiceSchedule.Category.OTOKOSHI:
        return ServiceSchedule.Category.OTOKOSHI.label
    return ""


class ServiceScheduleEditForm(forms.ModelForm):
    show_3_year_links = forms.BooleanField(
        required=False,
        label="3年前まで出す",
        help_text="通常は昨年分まで表示します。チェックすると3年前まで広げて候補一覧を再表示します。",
        widget=forms.CheckboxInput(
            attrs={
                "data-link-horizon-toggle": "1",
                "data-link-horizon-query-param": "show_3_year_links",
            }
        ),
    )
    show_10_year_links = forms.BooleanField(
        required=False,
        label="10年先まで出す",
        help_text="通常は今後2年まで表示します。チェックすると10年先まで広げて候補一覧を再表示します。",
        widget=forms.CheckboxInput(
            attrs={
                "data-link-horizon-toggle": "1",
                "data-link-horizon-query-param": "show_10_year_links",
            }
        ),
    )
    computed_target_date_display = forms.CharField(
        required=False,
        label="本当の命日",
        disabled=True,
    )
    scheduled_time = forms.TypedChoiceField(
        required=False,
        label="予定時刻",
        choices=HALF_HOUR_TIME_CHOICES,
        coerce=_coerce_optional_time,
        empty_value=None,
    )
    linked_candidate_tokens = forms.MultipleChoiceField(
        required=False,
        label="一緒に勤める他の回忌候補",
        widget=forms.CheckboxSelectMultiple,
        help_text=(
            "同じ家の他の故人に加え、必要に応じて同一故人の初盆も含めて、"
            "昨年分から今後2年までの回忌候補を一緒に勤める対象として選びます。"
            "`【過去】` は既に基準日を過ぎた候補です。"
        ),
    )
    completed_link_candidate_tokens = forms.MultipleChoiceField(
        required=False,
        disabled=True,
        label="勤修済みの回忌（参照のみ）",
        widget=forms.CheckboxSelectMultiple,
        help_text="すでに勤修済みのため、この法要へのリンク対象には選べません。",
    )
    linked_schedule_ids = forms.MultipleChoiceField(
        required=False,
        label="リンク済み法要",
        widget=forms.CheckboxSelectMultiple,
        help_text="チェックを外した対象は、この法要リンクから外します。",
    )
    reset_unlinked_schedules = forms.BooleanField(
        required=False,
        label="外した対象は自動で削除する",
        help_text="チェックを外した手入力法要は自動で削除し、取込由来の予定レコードは従来どおり未設定へ戻します。",
        initial=True,
        disabled=True,
    )
    apply_to_linked_group = forms.BooleanField(
        required=False,
        label="リンク済み法要にも同じ更新を反映",
        help_text="日時・状態・場所・メモなどを、同じ法要リンクに入っている対象へまとめて反映します。",
        initial=True,
    )

    class Meta:
        model = ServiceSchedule
        fields = [
            "category",
            "service_label",
            "subject_name",
            "link_group_key",
            "scheduled_date",
            "scheduled_time",
            "completed_on",
            "location",
            "status",
            "notes",
            "external_calendar_ref",
        ]
        widgets = {
            "scheduled_date": forms.DateInput(attrs={"type": "date"}),
            "completed_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(
        self,
        *args,
        link_candidate_choices: list[tuple[str, str]] | None = None,
        completed_link_candidate_choices: list[tuple[str, str]] | None = None,
        linked_schedule_choices: list[tuple[str, str]] | None = None,
        linked_schedule_initial: list[str] | None = None,
        show_link_range_toggle: bool = False,
        show_3_year_links_initial: bool = False,
        show_10_year_links_initial: bool = False,
        show_link_candidates: bool = False,
        show_completed_link_candidates: bool = False,
        show_linked_schedule_choices: bool = False,
        show_apply_to_linked_group: bool = False,
        target_date_initial: date | None = None,
        target_date_label: str = "本当の命日",
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        resolved_category = (
            str(self.data.get("category") or "").strip()
            if self.is_bound
            else str(self.initial.get("category") or getattr(self.instance, "category", "") or "").strip()
        )
        resolved_service_label = (
            str(self.data.get("service_label") or "").strip()
            if self.is_bound
            else str(
                self.initial.get("service_label") or getattr(self.instance, "service_label", "") or ""
            ).strip()
        )
        is_generic_other_event = _is_generic_other_event(
            resolved_category,
            resolved_service_label,
        )
        household_only_event_label = _household_only_event_label(resolved_category)
        self.fields["category"].choices = _service_schedule_category_choices()
        self.fields["category"].label = "種別"
        self.fields["service_label"].label = "タイトル" if is_generic_other_event else "法要名"
        self.fields["subject_name"].label = "対象故人"
        self.fields["scheduled_date"].label = "予定日"
        self.fields["completed_on"].label = "実施日"
        self.fields["location"].label = "場所"
        self.fields["status"].label = "状態"
        self.fields["notes"].label = "メモ"
        self.fields["external_calendar_ref"].label = "カレンダー参照"
        self.fields["external_calendar_ref"].widget = forms.HiddenInput()
        self.fields["link_group_key"].widget = forms.HiddenInput()
        self.fields["computed_target_date_display"].label = (
            "参考日" if is_generic_other_event else target_date_label
        )
        target_date_text = target_date_initial.isoformat() if target_date_initial else ""
        self.fields["computed_target_date_display"].initial = target_date_text
        self.fields["computed_target_date_display"].help_text = (
            "必要なときだけ確認する参考表示です。保存はしません。"
            if is_generic_other_event
            else "故人の命日から自動表示します。保存はしません。"
        )
        if is_generic_other_event:
            self.fields["subject_name"].widget = forms.HiddenInput()
            self.initial["subject_name"] = ""
            self.fields["subject_name"].initial = ""
        if household_only_event_label:
            self.fields["service_label"].required = False
            self.fields["service_label"].widget = forms.HiddenInput()
            self.initial["service_label"] = household_only_event_label
            self.fields["service_label"].initial = household_only_event_label
        scheduled_time_value = self.instance.scheduled_time if getattr(self.instance, "pk", None) else None
        if scheduled_time_value is not None:
            time_key = scheduled_time_value.strftime("%H:%M")
            existing_choices = dict(self.fields["scheduled_time"].choices)
            if time_key not in existing_choices:
                self.fields["scheduled_time"].choices = [
                    *self.fields["scheduled_time"].choices,
                    (time_key, time_key),
                ]
            self.initial["scheduled_time"] = time_key
            self.fields["scheduled_time"].initial = time_key
        else:
            self.initial["scheduled_time"] = "10:00"
            self.fields["scheduled_time"].initial = "10:00"
        is_manual_schedule = (
            getattr(self.instance, "record_origin", "") == ServiceSchedule.Origin.MANUAL
            or getattr(self.instance, "source_table", "") == "manual_service_schedule"
        )
        if is_manual_schedule:
            self.fields["status"].choices = [
                choice
                for choice in self.fields["status"].choices
                if choice[0] != ServiceSchedule.Status.CANDIDATE
                or getattr(self.instance, "status", "") == ServiceSchedule.Status.CANDIDATE
            ]
            if not getattr(self.instance, "pk", None) and (
                not self.initial.get("status")
                or self.initial.get("status") == ServiceSchedule.Status.CANDIDATE
            ):
                self.initial["status"] = ServiceSchedule.Status.SCHEDULED
                self.fields["status"].initial = ServiceSchedule.Status.SCHEDULED
        self.order_fields(
            [
                "category",
                "service_label",
                "subject_name",
                "computed_target_date_display",
                "scheduled_date",
                "scheduled_time",
                "completed_on",
                "location",
                "status",
                "notes",
                "external_calendar_ref",
                "show_3_year_links",
                "show_10_year_links",
                "linked_candidate_tokens",
                "completed_link_candidate_tokens",
                "linked_schedule_ids",
                "reset_unlinked_schedules",
                "apply_to_linked_group",
                "link_group_key",
            ]
        )
        if show_link_range_toggle:
            self.initial["show_3_year_links"] = show_3_year_links_initial
            self.fields["show_3_year_links"].initial = show_3_year_links_initial
            self.initial["show_10_year_links"] = show_10_year_links_initial
            self.fields["show_10_year_links"].initial = show_10_year_links_initial
            lookback_label = "3年前" if show_3_year_links_initial else "昨年分"
            lookahead_label = "10年" if show_10_year_links_initial else "2年"
            self.fields["linked_candidate_tokens"].help_text = (
                "同じ家の他の故人に加え、必要に応じて同一故人の初盆も含めて、"
                f"{lookback_label}から今後{lookahead_label}までの回忌候補を"
                "一緒に勤める対象として選びます。"
                "`【過去】` は既に基準日を過ぎた候補です。"
            )
        else:
            self.fields.pop("show_3_year_links", None)
            self.fields.pop("show_10_year_links", None)
        if show_link_candidates:
            self.fields["linked_candidate_tokens"].choices = link_candidate_choices or []
        else:
            self.fields.pop("linked_candidate_tokens", None)
        if show_completed_link_candidates:
            self.fields["completed_link_candidate_tokens"].choices = (
                completed_link_candidate_choices or []
            )
        else:
            self.fields.pop("completed_link_candidate_tokens", None)
        if show_linked_schedule_choices:
            self.fields["linked_schedule_ids"].choices = linked_schedule_choices or []
            self.initial["linked_schedule_ids"] = linked_schedule_initial or []
            self.fields["linked_schedule_ids"].initial = linked_schedule_initial or []
        else:
            self.fields.pop("linked_schedule_ids", None)
            self.fields.pop("reset_unlinked_schedules", None)
        if not show_apply_to_linked_group:
            self.fields.pop("apply_to_linked_group", None)

    def clean(self):
        cleaned_data = super().clean()
        household_only_event_label = _household_only_event_label(cleaned_data.get("category"))
        if household_only_event_label:
            cleaned_data["service_label"] = household_only_event_label
            cleaned_data["subject_name"] = ""
        return cleaned_data
