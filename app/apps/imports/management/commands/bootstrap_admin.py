from __future__ import annotations

import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the initial admin user for TempleDB."

    def handle(self, *args, **options) -> None:
        User = get_user_model()
        existing = User.objects.filter(username="admin").first()
        if existing is not None:
            self.stdout.write(self.style.WARNING("admin already exists."))
            return

        password = getpass.getpass("Admin password: ")
        password_confirm = getpass.getpass("Admin password (again): ")
        if not password:
            raise SystemExit("Password cannot be empty.")
        if password != password_confirm:
            raise SystemExit("Passwords do not match.")

        user = User.objects.create_superuser(username="admin", password=password)
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=["is_staff", "is_superuser"])
        self.stdout.write(self.style.SUCCESS("Created admin user."))
