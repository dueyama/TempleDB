from django import forms

from apps.imports.forms import PersonEditForm
from apps.imports.models import FAMILY_CATEGORY_MEMORIAL


class PersonCalendarEditForm(PersonEditForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.is_deceased or self.instance.family_category == FAMILY_CATEGORY_MEMORIAL:
            self.fields["sync_google_calendar"] = forms.BooleanField(
                required=False,
                initial=True,
                label="Googleカレンダーにも同期する",
                help_text="関連する法要予定の表示内容を同期します。予定の日時・状態は変更しません。オフでも寺務内の名前は修正します。",
            )
