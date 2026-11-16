import os

from vercel_demo.runtime import ROOT  # noqa: F401

os.environ["DJANGO_SETTINGS_MODULE"] = "vercel_demo.settings"

from django.core.management import execute_from_command_line  # noqa: E402

execute_from_command_line()
