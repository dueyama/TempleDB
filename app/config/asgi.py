import os

from django.core.asgi import get_asgi_application

from config.env import load_env_file


def _assert_runtime_identity() -> None:
    from apps.core.services.runtime_identity_guard import assert_web_runtime_identity

    assert_web_runtime_identity()

load_env_file()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
_assert_runtime_identity()
