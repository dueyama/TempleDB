from django import forms

from apps.imports.forms import ServiceScheduleEditForm
from apps.imports.models import ServiceSchedule
from apps.office.services.funeral_first_seventh import existing_first_seventh


class FuneralScheduleEditForm(ServiceScheduleEditForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if (
            self.instance.pk
            and self.instance.category == ServiceSchedule.Category.FUNERAL
            and self.instance.person_id
        ):
            existing = existing_first_seventh(self.instance)
            linked = (
                existing is not None
                and existing.category == ServiceSchedule.Category.CHUIN
                and existing.person_id == self.instance.person_id
                and existing.household_id == self.instance.household_id
                and existing.deleted_at is None
                and self.instance.deleted_at is None
                and bool(self.instance.link_group_key.strip())
                and existing.link_group_key == self.instance.link_group_key
            )
            if linked:
                help_text = (
                    "葬儀と初七日は連動しています。どちらの編集画面でも、変更した日時・場所・完了状態を相手へ反映します。メモは個別に保持します。"
                )
            elif existing:
                help_text = "初七日は別の予定として登録済みです。変更は初七日の編集画面で行ってください。"
            else:
                help_text = (
                    "保存時に初七日を葬儀と同じ日時・場所・状態で登録します。登録後は、どちらの編集画面でも日程・完了状態を変更できます。メモは個別に保持します。"
                )
            self.fields["include_first_seventh"] = forms.BooleanField(
                required=False,
                label="初七日を一緒に勤める",
                disabled=existing is not None,
                help_text=help_text,
            )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("include_first_seventh"):
            if cleaned.get("category") != ServiceSchedule.Category.FUNERAL:
                self.add_error("include_first_seventh", "葬儀の場合だけ指定できます。")
            if not cleaned.get("scheduled_date"):
                self.add_error(
                    "scheduled_date", "初七日を一緒に勤める葬儀の日付を入力してください。"
                )
        return cleaned
