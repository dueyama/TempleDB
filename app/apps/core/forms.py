from __future__ import annotations

from pathlib import PurePath

from django import forms
from django.core.exceptions import ValidationError

from .models import (
    DEFAULT_SERVICE_SCHEDULE_SUTRA_CYCLE_TEXT,
    DEFAULT_TEMPLE_ADDRESS,
    DEFAULT_TEMPLE_CHIEF_PRIEST_NAME,
    DEFAULT_TEMPLE_NAME,
    DEFAULT_TEMPLE_PHONE,
    DEFAULT_TEMPLE_POSTAL_CODE,
    DEFAULT_TEMPLE_SECT,
    DatabaseBackupSetting,
    GoogleCalendarSyncSetting,
    TempleIdentitySetting,
)
from .services import backup, temple_identity, ui_appearance


class DatabaseBackupSettingForm(forms.Form):
    volume_name = forms.ChoiceField(label="外部ディスク", required=False)
    subdirectory_name = forms.CharField(
        label="保存フォルダ",
        max_length=255,
        initial="TempleDBBackups",
        help_text="外部ディスク直下に作るサブフォルダ名です。",
    )
    daily_enabled = forms.BooleanField(
        label="毎日1回の自動バックアップを有効にする",
        required=False,
        initial=True,
    )
    weekly_verification_enabled = forms.BooleanField(
        label="7日ごとの自動テスト復元を有効にする",
        required=False,
        initial=True,
        help_text=(
            "認証済みアクセス時に期限を判定し、最新の成功バックアップを一時DBへ復元します。"
            "現在のTempleDBは上書きせず、確認後に一時DBを削除します。"
        ),
    )
    retention_count = forms.IntegerField(
        label="保持世代数",
        min_value=1,
        max_value=365,
        initial=30,
        help_text="成功したバックアップを新しい順で何世代残すかを指定します。",
    )

    def __init__(self, *args, setting: DatabaseBackupSetting | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setting = setting
        volumes = backup.list_available_volumes()
        self.fields["volume_name"].choices = [(entry["name"], entry["label"]) for entry in volumes]
        if not self.is_bound:
            initial = backup.split_destination_path(setting.destination_path if setting else "")
            if initial is not None:
                volume_name, subdirectory_name = initial
                self.initial.setdefault("volume_name", volume_name)
                self.initial.setdefault("subdirectory_name", subdirectory_name)
            elif volumes:
                self.initial.setdefault("volume_name", volumes[0]["name"])
            if setting is not None:
                self.initial.setdefault("daily_enabled", setting.daily_enabled)
                self.initial.setdefault(
                    "weekly_verification_enabled",
                    setting.weekly_verification_enabled,
                )
                self.initial.setdefault("retention_count", setting.retention_count)
        if not volumes:
            self.fields[
                "volume_name"
            ].help_text = "現在 /Volumes に利用可能な外部ディスクがありません。"

    def clean_volume_name(self) -> str:
        volume_name = (self.cleaned_data.get("volume_name") or "").strip()
        available = {choice[0] for choice in self.fields["volume_name"].choices}
        if not volume_name:
            raise ValidationError("外部ディスクを選択してください。")
        if volume_name not in available:
            raise ValidationError("選択した外部ディスクは現在利用できません。")
        return volume_name

    def clean_subdirectory_name(self) -> str:
        raw_value = (self.cleaned_data.get("subdirectory_name") or "").strip()
        if not raw_value:
            return "TempleDBBackups"
        pure_path = PurePath(raw_value)
        if pure_path.is_absolute():
            raise ValidationError(
                "保存フォルダは外部ディスク直下からの相対パスで指定してください。"
            )
        if any(part in {"", ".", ".."} for part in pure_path.parts):
            raise ValidationError("保存フォルダには '.' や '..' を含められません。")
        return str(pure_path)

    def save_to_setting(self, setting: DatabaseBackupSetting) -> DatabaseBackupSetting:
        destination_path = backup.ensure_destination_directory(
            self.cleaned_data["volume_name"],
            self.cleaned_data["subdirectory_name"],
        )
        setting.destination_path = str(destination_path)
        setting.daily_enabled = bool(self.cleaned_data["daily_enabled"])
        setting.weekly_verification_enabled = bool(
            self.cleaned_data["weekly_verification_enabled"]
        )
        setting.retention_count = int(self.cleaned_data["retention_count"])
        setting.save()
        return setting


class TempleIdentitySettingForm(forms.ModelForm):
    class Meta:
        model = TempleIdentitySetting
        fields = [
            "temple_sect",
            "temple_name",
            "temple_postal_code",
            "temple_address",
            "temple_phone",
            "chief_priest_name",
            "service_schedule_sutra_cycle",
        ]
        labels = {
            "temple_sect": "宗派名",
            "temple_name": "寺院名",
            "temple_postal_code": "郵便番号",
            "temple_address": "住所",
            "temple_phone": "電話",
            "chief_priest_name": "住職名",
            "service_schedule_sutra_cycle": "法要印刷の読経順",
        }
        help_texts = {
            "temple_sect": "翌年回忌案内の署名既定に使う宗派名です。",
            "temple_name": "年忌表や翌年回忌案内の署名既定に使う寺院名です。",
            "temple_postal_code": "翌年回忌案内などで使う寺院の郵便番号です。",
            "temple_address": "翌年回忌案内の署名既定に使う住所です。",
            "temple_phone": "印刷する電話番号を漢数字込みで管理します。",
            "chief_priest_name": "案内文面や帳票で使う住職名です。",
            "service_schedule_sutra_cycle": (
                "1行に1つずつ入力します。印刷カードでは 満中陰 → 一周忌 → 三回忌 → その後の回忌 "
                "の順にローテーションします。"
            ),
        }
        widgets = {
            "temple_sect": forms.TextInput(attrs={"placeholder": DEFAULT_TEMPLE_SECT or "宗派名"}),
            "temple_name": forms.TextInput(attrs={"placeholder": DEFAULT_TEMPLE_NAME or "寺院名"}),
            "temple_postal_code": forms.TextInput(attrs={"placeholder": DEFAULT_TEMPLE_POSTAL_CODE or "郵便番号"}),
            "temple_address": forms.TextInput(attrs={"placeholder": DEFAULT_TEMPLE_ADDRESS or "住所"}),
            "temple_phone": forms.TextInput(attrs={"placeholder": DEFAULT_TEMPLE_PHONE or "電話番号"}),
            "chief_priest_name": forms.TextInput(attrs={"placeholder": DEFAULT_TEMPLE_CHIEF_PRIEST_NAME or "住職名"}),
            "service_schedule_sutra_cycle": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": DEFAULT_SERVICE_SCHEDULE_SUTRA_CYCLE_TEXT,
                }
            ),
        }

    def clean_temple_name(self) -> str:
        return (self.cleaned_data.get("temple_name") or "").strip()

    def clean_temple_sect(self) -> str:
        return (self.cleaned_data.get("temple_sect") or "").strip()

    def clean_temple_postal_code(self) -> str:
        return (self.cleaned_data.get("temple_postal_code") or "").strip()

    def clean_temple_address(self) -> str:
        return (self.cleaned_data.get("temple_address") or "").strip()

    def clean_temple_phone(self) -> str:
        return (self.cleaned_data.get("temple_phone") or "").strip()

    def clean_chief_priest_name(self) -> str:
        return (self.cleaned_data.get("chief_priest_name") or "").strip()

    def clean_service_schedule_sutra_cycle(self) -> str:
        normalized = temple_identity.normalize_service_schedule_sutra_cycle(
            self.cleaned_data.get("service_schedule_sutra_cycle")
        )
        return "\n".join(normalized)


class UiAppearancePreferenceForm(forms.Form):
    theme = forms.ChoiceField(
        label="表示テーマ",
        choices=ui_appearance.UI_THEME_CHOICES,
        widget=forms.RadioSelect,
        help_text="TempleDB全体の操作ボタンの見た目だけを切り替えます。",
    )


class GoogleCalendarSyncSettingForm(forms.ModelForm):
    class Meta:
        model = GoogleCalendarSyncSetting
        fields = ["enabled", "calendar_id"]
        labels = {
            "enabled": "Google カレンダー同期を有効にする",
            "calendar_id": "Google カレンダー ID",
        }
        help_texts = {
            "calendar_id": "TempleDB 専用の非公開 Google カレンダー ID を入力します。",
        }

    def clean_calendar_id(self) -> str:
        return (self.cleaned_data.get("calendar_id") or "").strip()
