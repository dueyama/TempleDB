from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.imports.forms import UserManagementCreateForm, UserManagementPasswordResetForm
from apps.office import services
from apps.office.views.common import _ensure_superuser
from apps.office.web_support import _user_management_redirect_url


def user_management(request: HttpRequest) -> HttpResponse:
    active_source_id = services.operational_source_id()
    _ensure_superuser(request)
    User = get_user_model()
    create_form = UserManagementCreateForm(prefix="create")
    selected_password_user = None
    password_form = None
    password_user_value = (request.GET.get("password_user") or request.POST.get("password_user") or "").strip()
    if password_user_value.isdigit():
        selected_password_user = get_object_or_404(User, pk=int(password_user_value))
        password_form = UserManagementPasswordResetForm(
            user=selected_password_user,
            prefix="password",
        )

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "create_user":
            create_form = UserManagementCreateForm(request.POST, prefix="create")
            if create_form.is_valid():
                created_user = create_form.save()
                messages.success(request, f"ユーザー {created_user.username} を作成しました。")
                return redirect(_user_management_redirect_url())
            messages.error(request, "ユーザー作成に失敗しました。入力内容を確認してください。")
        elif action == "toggle_active":
            user = get_object_or_404(User, pk=request.POST.get("user_id"))
            if user.pk == request.user.pk:
                messages.error(request, "自分自身の有効/停止はこの画面から変更できません。")
                return redirect(_user_management_redirect_url())
            elif user.is_active and user.is_superuser:
                other_active_superusers = User._default_manager.filter(
                    is_superuser=True,
                    is_active=True,
                ).exclude(pk=user.pk)
                if not other_active_superusers.exists():
                    messages.error(request, "最後の有効な管理者は停止できません。")
                    return redirect(_user_management_redirect_url())
                user.is_active = False
                user.save(update_fields=["is_active"])
                messages.success(request, f"ユーザー {user.username} を停止しました。")
                return redirect(_user_management_redirect_url())
            user.is_active = not user.is_active
            user.save(update_fields=["is_active"])
            status_label = "有効化" if user.is_active else "停止"
            messages.success(request, f"ユーザー {user.username} を{status_label}しました。")
            return redirect(_user_management_redirect_url())
        elif action == "toggle_admin":
            user = get_object_or_404(User, pk=request.POST.get("user_id"))
            if user.pk == request.user.pk:
                messages.error(request, "自分自身の管理者権限はこの画面から変更できません。")
                return redirect(_user_management_redirect_url())
            elif user.is_superuser:
                other_superusers = User._default_manager.filter(is_superuser=True).exclude(pk=user.pk)
                if not other_superusers.exists():
                    messages.error(request, "最後の管理者は一般ユーザーへ変更できません。")
                    return redirect(_user_management_redirect_url())
                user.is_staff = False
                user.is_superuser = False
                user.save(update_fields=["is_staff", "is_superuser"])
                messages.success(request, f"ユーザー {user.username} を一般ユーザーへ変更しました。")
                return redirect(_user_management_redirect_url())
            user.is_staff = True
            user.is_superuser = True
            user.save(update_fields=["is_staff", "is_superuser"])
            messages.success(request, f"ユーザー {user.username} を管理者に変更しました。")
            return redirect(_user_management_redirect_url())
        elif action == "set_password":
            selected_password_user = get_object_or_404(User, pk=request.POST.get("user_id"))
            password_form = UserManagementPasswordResetForm(
                request.POST,
                user=selected_password_user,
                prefix="password",
            )
            if password_form.is_valid():
                password_form.save()
                if selected_password_user.pk == request.user.pk:
                    update_session_auth_hash(request, selected_password_user)
                messages.success(request, f"ユーザー {selected_password_user.username} のパスワードを更新しました。")
                return redirect(_user_management_redirect_url())
            messages.error(request, "パスワード更新に失敗しました。入力内容を確認してください。")
        else:
            messages.error(request, "不明な操作です。")
            return redirect(_user_management_redirect_url())

    user_rows = list(
        User._default_manager.order_by("username").values(
            "id",
            "username",
            "is_active",
            "is_staff",
            "is_superuser",
            "last_login",
            "date_joined",
        )
    )
    context = {
        "selected_source_id": active_source_id,
        "create_form": create_form,
        "password_form": password_form,
        "selected_password_user": selected_password_user,
        "user_rows": user_rows,
        "user_count": User._default_manager.count(),
        "active_user_count": User._default_manager.filter(is_active=True).count(),
        "admin_user_count": User._default_manager.filter(is_superuser=True).count(),
    }
    return render(request, "office/user_management.html", context)


__all__ = ["user_management"]
