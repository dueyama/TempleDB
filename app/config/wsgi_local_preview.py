"""Local synthetic preview does not select or alter the production `current`."""
from pathlib import Path

from django.conf import settings
from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()

from apps.core.models import DatabaseRuntimeIdentity  # noqa: E402

expected = Path(__file__).resolve().parents[1] / "instances/local-preview"
assert settings.TEMPLEDB_DEMO_MODE is True
assert settings.TEMPLEDB_DATABASE_ENGINE == "sqlite"
assert settings.TEMPLEDB_RUNTIME_ROLE == "staging"
assert settings.TEMPLEDB_STAGING_ALLOW_OPENAI is False
assert Path(settings.TEMPLEDB_TENANT_ROOT).resolve() == expected
assert Path(settings.DATABASES["default"]["NAME"]).resolve() == expected / "preview.sqlite3"
assert DatabaseRuntimeIdentity.objects.get(singleton_key=1).runtime_kind == "demo"
