import os

from django.core.wsgi import get_wsgi_application

from config.env import load_env_file


def _assert_runtime_identity() -> None:
    from apps.core.services.runtime_identity_guard import assert_web_runtime_identity

    assert_web_runtime_identity()

load_env_file()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
_assert_runtime_identity()
