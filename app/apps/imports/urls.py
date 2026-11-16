from django.contrib.auth.decorators import login_required
from django.urls import path

from . import console_views

app_name = "imports"


def protected(route, view, kwargs=None, name=None):
    return path(route, login_required(view), kwargs=kwargs, name=name)

urlpatterns = [
    protected("", console_views.console, name="console"),
    protected("sources/register/", console_views.register_source, name="register_source"),
    protected("sources/set-default/", console_views.set_default_source, name="set_default_source"),
    protected("run/<str:action>/", console_views.run_action, name="run_action"),
]
