"""Explicit synthetic preview; never a production startup entrypoint."""
from .settings import *  # noqa: F403

WSGI_APPLICATION = "config.wsgi_local_preview.application"
