"""Generate the demo seed from public JSON; never reads a supplied database."""
import os
import secrets

os.environ["TEMPLEDB_VERCEL_BUILD"] = "1"
os.environ.setdefault("DJANGO_SECRET_KEY", secrets.token_urlsafe(48))
os.environ["DJANGO_SETTINGS_MODULE"] = "vercel_demo.settings"

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402

from vercel_demo.runtime import ROOT, SEED, validate_seed  # noqa: E402

call_command("migrate", interactive=False, verbosity=0)
call_command(
    "load_demo_dataset", dataset_id="synthetic_demo_v1",
    dataset_root=str(ROOT / "datasets/synthetic_demo_v1"), username="demo", password="demo",
    verbosity=0,
)
validate_seed(SEED)
print("Verified a newly generated synthetic-only demo seed")
