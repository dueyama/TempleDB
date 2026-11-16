from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy
from django.views.generic.base import RedirectView

from apps.core.views_auth import SafeNextPasswordChangeView

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "password/change/",
        SafeNextPasswordChangeView.as_view(
            template_name="registration/password_change_form.html",
            success_url=reverse_lazy("password_change_done"),
        ),
        name="password_change",
    ),
    path(
        "password/change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="registration/password_change_done.html",
        ),
        name="password_change_done",
    ),
    path(
        "favicon.ico",
        RedirectView.as_view(url="/static/icons/favicon.ico", permanent=False),
    ),
    path(
        "apple-touch-icon.png",
        RedirectView.as_view(url="/static/icons/apple-touch-icon.png", permanent=False),
    ),
    path(
        "apple-touch-icon-precomposed.png",
        RedirectView.as_view(
            url="/static/icons/apple-touch-icon-precomposed.png",
            permanent=False,
        ),
    ),
    path("", include(("apps.office.urls", "office"), namespace="office")),
    path("imports/", include(("apps.imports.urls", "imports"), namespace="imports")),
]
