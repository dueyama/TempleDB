from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.imports.models import Household, LegacySource
from apps.imports.source_runtime import source_summary


class EmptyBootstrapTests(TestCase):
    def test_checks_work_before_any_source_or_business_row_is_registered(self):
        self.assertEqual(LegacySource.objects.count(), 0)
        self.assertEqual(Household.objects.count(), 0)
        # This previously recursed when the public bootstrap contained no sources.
        summary = source_summary()
        self.assertIsInstance(summary, dict)
        call_command("check", stdout=StringIO())
        self.assertEqual(LegacySource.objects.count(), 0)
        self.assertEqual(Household.objects.count(), 0)
