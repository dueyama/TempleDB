from __future__ import annotations

from datetime import date, time
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, override_settings

from apps.core.models import DatabaseRuntimeIdentity
from apps.imports.models import Household, LegacySource, Person, ServiceSchedule
from apps.office.services.service_schedule_link_groups import _apply_linked_group_updates


class StarterMaintenanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        if connection.vendor != "sqlite" or not settings.TEMPLEDB_DEMO_MODE:
            raise RuntimeError("Use bin/test_maintenance.py with its isolated synthetic DB")
        call_command(
            "load_demo_dataset",
            dataset_root=str(settings.BASE_DIR.parent / "datasets" / "synthetic_demo_v1"),
            stdout=StringIO(),
        )

    def test_database_and_generated_paths_are_isolated(self):
        workspace = settings.BASE_DIR.parent
        self.assertEqual(connection.vendor, "sqlite")
        self.assertEqual(Path(connection.settings_dict["NAME"]), workspace / "runtime/test.sqlite3")
        self.assertEqual(settings.TEMPLEDB_TENANT_ROOT, settings.BASE_DIR)
        self.assertEqual(DatabaseRuntimeIdentity.objects.get(singleton_key=1).runtime_kind, "demo")

    def test_fresh_database_has_all_migrations(self):
        executor = MigrationExecutor(connection)
        self.assertEqual(executor.migration_plan(executor.loader.graph.leaf_nodes()), [])

    def test_synthetic_household_person_relations(self):
        self.assertEqual(list(LegacySource.objects.values_list("source_id", flat=True)), ["demo-synthetic-rich"])
        self.assertGreaterEqual(Household.objects.count(), 100)
        self.assertGreaterEqual(Person.objects.count(), 300)
        self.assertGreaterEqual(ServiceSchedule.objects.count(), 150)
        self.assertFalse(ServiceSchedule.objects.filter(person__isnull=False, person_uid="").exists())

    def test_login_and_logout(self):
        self.assertFalse(self.client.login(username="demo", password="incorrect-test-password"))
        self.assertTrue(self.client.login(username="demo", password="demo"))
        self.assertEqual(self.client.get("/").status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get("/households/").status_code, 302)

    def test_anonymous_requests_require_login(self):
        for path in ("/households/", "/services/", "/settings/backup/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login/", response.url)

    def test_major_pages_render(self):
        self.client.force_login(get_user_model().objects.get(username="demo"))
        for path in ("/", "/households/", "/services/", "/settings/accounting/", "/prints/", "/settings/backup/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("text/html", response["Content-Type"])

    def test_service_schedule_planning_and_completion(self):
        schedule = ServiceSchedule.objects.order_by("pk").first()
        self.assertIsNotNone(schedule)
        schedule.scheduled_date = date(2030, 5, 12)
        schedule.scheduled_time = time(10, 30)
        schedule.status = ServiceSchedule.Status.SCHEDULED
        schedule.completed_on = None
        schedule.save()
        schedule.refresh_from_db()
        self.assertEqual(schedule.status, ServiceSchedule.Status.SCHEDULED)
        self.assertIsNone(schedule.completed_on)
        schedule.status = ServiceSchedule.Status.COMPLETED
        schedule.completed_on = date(2030, 5, 12)
        schedule.save()
        schedule.refresh_from_db()
        self.assertEqual(schedule.status, ServiceSchedule.Status.COMPLETED)
        self.assertEqual(schedule.completed_on, date(2030, 5, 12))

    def test_linked_services_share_completion_and_record_history(self):
        base, sibling = list(ServiceSchedule.objects.order_by("pk")[:2])
        for schedule in (base, sibling):
            schedule.link_group_key = "public-maintenance-linked-group"
            schedule.save()
        base.status = ServiceSchedule.Status.COMPLETED
        base.completed_on = date(2030, 5, 12)
        base.scheduled_date = date(2030, 5, 12)
        base.save()
        logs = _apply_linked_group_updates(
            schedule=base, apply_updates=True,
            editor_label="public-test", change_note="synthetic linked completion",
        )
        sibling.refresh_from_db()
        self.assertEqual(sibling.status, ServiceSchedule.Status.COMPLETED)
        self.assertEqual(sibling.completed_on, base.completed_on)
        self.assertEqual(sibling.scheduled_date, base.scheduled_date)
        self.assertEqual(len(logs), 1)

    @override_settings(TEMPLEDB_PRODUCT_SQLITE_MODE=True, TEMPLEDB_DEMO_MODE=False)
    def test_product_mode_refuses_synthetic_seed_even_with_force(self):
        before = Person.objects.count()
        with self.assertRaises(CommandError):
            call_command("load_demo_dataset", force=True, stdout=StringIO())
        self.assertEqual(Person.objects.count(), before)
