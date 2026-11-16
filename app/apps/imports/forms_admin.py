from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model, password_validation

from .models import District


class UserManagementCreateForm(forms.Form):
    username = forms.CharField(
        required=True,
        label="ユーザー名",
        max_length=150,
    )
    password1 = forms.CharField(
        required=True,
        label="初期パスワード",
        strip=False,
        widget=forms.PasswordInput(render_value=False),
    )
    password2 = forms.CharField(
        required=True,
        label="初期パスワード（確認）",
        strip=False,
        widget=forms.PasswordInput(render_value=False),
    )
    is_admin = forms.BooleanField(
        required=False,
        label="管理者にする",
        help_text="オンで Django Admin とユーザー管理ページを使えます。",
    )
    is_active = forms.BooleanField(
        required=False,
        initial=True,
        label="有効",
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.user_model = get_user_model()

    def clean_username(self) -> str:
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            raise forms.ValidationError("ユーザー名を入力してください。")
        if self.user_model._default_manager.filter(username=username).exists():
            raise forms.ValidationError("そのユーザー名は既に使われています。")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1") or ""
        password2 = cleaned_data.get("password2") or ""
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "確認用パスワードが一致しません。")
        if password1:
            try:
                password_validation.validate_password(password1)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned_data

    def save(self):
        username = self.cleaned_data["username"]
        is_admin = bool(self.cleaned_data.get("is_admin"))
        is_active = bool(self.cleaned_data.get("is_active"))
        user = self.user_model(
            username=username,
            is_active=is_active,
            is_staff=is_admin,
            is_superuser=is_admin,
        )
        user.set_password(self.cleaned_data["password1"])
        user.save()
        return user


class UserManagementPasswordResetForm(forms.Form):
    new_password1 = forms.CharField(
        required=True,
        label="新しいパスワード",
        strip=False,
        widget=forms.PasswordInput(render_value=False),
    )
    new_password2 = forms.CharField(
        required=True,
        label="新しいパスワード（確認）",
        strip=False,
        widget=forms.PasswordInput(render_value=False),
    )

    def __init__(self, *args, user=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("new_password1") or ""
        password2 = cleaned_data.get("new_password2") or ""
        if password1 and password2 and password1 != password2:
            self.add_error("new_password2", "確認用パスワードが一致しません。")
        if password1:
            try:
                password_validation.validate_password(password1, self.user)
            except forms.ValidationError as exc:
                self.add_error("new_password1", exc)
        return cleaned_data

    def save(self) -> None:
        self.user.set_password(self.cleaned_data["new_password1"])
        self.user.save(update_fields=["password"])


class DistrictForm(forms.ModelForm):
    officer_person_key = forms.ChoiceField(
        required=False,
        label="地区役員",
        choices=[("", "未設定")],
        help_text="この地区に所属する現在帳の人から選びます。役員がいない地区は未設定のままにできます。",
    )

    class Meta:
        model = District
        fields = [
            "name",
            "short_name",
            "sort_order",
            "is_active",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(
        self,
        *args,
        officer_choices: list[tuple[str, str]] | None = None,
        initial_officer_key: str = "",
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._officer_choice_map = {value: label for value, label in (officer_choices or [])}
        self.fields["officer_person_key"].choices = [("", "未設定"), *(officer_choices or [])]
        self.fields["name"].label = "地区名"
        self.fields["short_name"].label = "略称"
        self.fields["sort_order"].label = "表示順"
        self.fields["is_active"].label = "有効"
        self.fields["notes"].label = "メモ"
        if initial_officer_key:
            if initial_officer_key not in dict(self.fields["officer_person_key"].choices):
                label = self._officer_choice_map.get(initial_officer_key, initial_officer_key)
                self.fields["officer_person_key"].choices = [
                    *self.fields["officer_person_key"].choices,
                    (initial_officer_key, f"{label}（現在は選択候補外）"),
                ]
            self.fields["officer_person_key"].initial = initial_officer_key

    def save(self, commit: bool = True):
        district = super().save(commit=False)
        if commit:
            district.save()
        return district
