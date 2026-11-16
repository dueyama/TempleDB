"""Current code on a disposable PostgreSQL copy; never production configuration."""
from .realdata_preview_guard import load_preview_record

_preview = load_preview_record()

from .settings import *  # noqa: E402,F403

WSGI_APPLICATION = "config.wsgi_realdata_preview.application"
ROOT_URLCONF = "config.urls_realdata_preview"
DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
TEMPLEDB_PREVIEW_INFO = {
    "snapshot_at": _preview["snapshot_at"], "generation": _preview["generation"],
    "run_id": Path(_preview["session_dir"]).name.removeprefix("preview-"),  # noqa: F405
}
SESSION_COOKIE_NAME = "templedb_preview_sessionid"
CSRF_COOKIE_NAME = "templedb_preview_csrftoken"
EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
MIDDLEWARE = list(MIDDLEWARE)  # noqa: F405
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware") + 1,
    "apps.core.middleware_realdata_preview.RealDataPreviewMiddleware",
)
STATIC_ROOT = str(Path(_preview["session_dir"]) / "staticfiles")  # noqa: F405
FILE_UPLOAD_TEMP_DIR = str(Path(_preview["session_dir"]) / "tmp")  # noqa: F405
