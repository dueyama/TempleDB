from __future__ import annotations

import os
from pathlib import Path

from config.runtime_paths import sqlite_db_path, tenant_root
from config.settings_helpers import (
    env_flag,
    resolve_allowed_hosts,
    resolve_csrf_trusted_origins,
    resolve_database_runtime,
    should_allow_sqlite_fallback,
)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLEDB_TENANT_ROOT = tenant_root()

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "unsafe-dev-key")
DEBUG = env_flag(os.environ.get("DJANGO_DEBUG"), default=True)
ALLOWED_HOSTS = resolve_allowed_hosts(os.environ.get("DJANGO_ALLOWED_HOSTS"), DEBUG)
TEMPLEDB_BASE_URL = os.environ.get("TEMPLEDB_BASE_URL", "").strip()
TEMPLEDB_EXTERNAL_BASE_URL = os.environ.get("TEMPLEDB_EXTERNAL_BASE_URL", "").strip()
TEMPLEDB_BACKUP_DESTINATION_PATH = os.environ.get(
    "TEMPLEDB_BACKUP_DESTINATION_PATH",
    "",
).strip()
TEMPLEDB_RECOVERY_HEALTH_PATH = os.environ.get("TEMPLEDB_RECOVERY_HEALTH_PATH", "").strip()
TEMPLEDB_RUNTIME_ROLE = (
    os.environ.get("TEMPLEDB_RUNTIME_ROLE", "primary").strip().lower() or "primary"
)
if TEMPLEDB_RUNTIME_ROLE not in {"primary", "staging", "standby"}:
    raise RuntimeError(
        "TEMPLEDB_RUNTIME_ROLE must be primary, staging, or standby."
    )
TEMPLEDB_STAGING_ALLOW_OPENAI = env_flag(
    os.environ.get("TEMPLEDB_STAGING_ALLOW_OPENAI"),
    default=False,
)
CSRF_TRUSTED_ORIGINS = resolve_csrf_trusted_origins(
    os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS"),
    TEMPLEDB_BASE_URL,
    TEMPLEDB_EXTERNAL_BASE_URL,
)
TEMPLEDB_TRUSTED_PROXY_HTTPS = env_flag(
    os.environ.get("TEMPLEDB_TRUSTED_PROXY_HTTPS"),
    default=False,
)
if TEMPLEDB_TRUSTED_PROXY_HTTPS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 3600
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
    # A tailnet hostname is not eligible for an application-owned preload policy,
    # and TempleDB must not make promises for subdomains it does not operate.
    SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
DATABASE_HOST = os.environ.get("DATABASE_HOST")
try:
    DATABASE_RUNTIME = resolve_database_runtime(
        os.environ,
        fallback_sqlite_path=sqlite_db_path(),
        allow_test_sqlite=should_allow_sqlite_fallback(),
        allow_product_sqlite_initialization=(
            os.environ.get("DJANGO_SETTINGS_MODULE")
            == "config.settings_product_sqlite_initialization"
        ),
    )
except ValueError as exc:
    raise RuntimeError(str(exc)) from exc
TEMPLEDB_DATABASE_ENGINE = DATABASE_RUNTIME.engine
TEMPLEDB_DEMO_MODE = DATABASE_RUNTIME.is_demo
TEMPLEDB_PRODUCT_SQLITE_MODE = DATABASE_RUNTIME.is_product_sqlite
TEMPLEDB_POSTGRESQL_DEMO_MODE = DATABASE_RUNTIME.is_postgresql_demo
TEMPLEDB_LEGACY_REIMPORT_ENABLED = env_flag(
    os.environ.get("TEMPLEDB_LEGACY_REIMPORT_ENABLED"),
    default=False,
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.core",
    "apps.office",
    "apps.imports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.DatabaseBackupScheduleMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.tenant_policy_labels",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if DATABASE_RUNTIME.engine == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DATABASE_NAME", "templedb"),
            "USER": os.environ.get("DATABASE_USER", "templedb"),
            "PASSWORD": os.environ.get("DATABASE_PASSWORD", "templedb"),
            "HOST": DATABASE_HOST,
            "PORT": os.environ.get("DATABASE_PORT", "5432"),
        }
    }
elif DATABASE_RUNTIME.engine == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATABASE_RUNTIME.sqlite_path,
            "OPTIONS": {
                "timeout": 30,
            },
        }
    }
else:
    raise RuntimeError(f"Unsupported TempleDB database engine: {DATABASE_RUNTIME.engine}")

LANGUAGE_CODE = "ja"
TIME_ZONE = "Asia/Tokyo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TEMPLEDB_ALLOWED_UI_THEMES = {"standard", "light"}
# Compatibility fallback for installations that have not yet saved
# config/tenant_preferences/ui_appearance.json from the settings screen.
TEMPLEDB_UI_THEME = os.environ.get("TEMPLEDB_UI_THEME", "standard")
