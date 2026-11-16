"""Local preview controls are never registered by the production URLconf."""
from django.urls import path

from apps.core.views_realdata_preview import exit_preview

from .urls import urlpatterns as application_urls

urlpatterns = [
    path("__preview/exit/", exit_preview, name="realdata_preview_exit"),
    *application_urls,
]
