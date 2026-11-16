from __future__ import annotations

import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

WEB_SYMBOLS = {"HttpRequest", "HttpResponse", "messages", "redirect", "render"}
COMPATIBILITY_FILES = {"__init__.py", "legacy_helpers.py"}


def forbidden_imports(source: str) -> list[str]:
    problems = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            if any(alias.name in WEB_SYMBOLS for alias in node.names):
                problems.append(f"{node.lineno}: request/response symbol")
            if node.module and node.module.startswith(("apps.office.views", "apps.imports.views")):
                problems.append(f"{node.lineno}: service imports views")
        elif isinstance(node, ast.Import):
            if any(alias.name.startswith(("apps.office.views", "apps.imports.views")) for alias in node.names):
                problems.append(f"{node.lineno}: service imports views")
    return problems


class ServiceLayerTests(SimpleTestCase):
    def test_normal_services_do_not_import_request_response_or_views(self):
        root = Path(settings.BASE_DIR) / "apps/office/services"
        files = [path for path in root.rglob("*.py") if path.name not in COMPATIBILITY_FILES]
        self.assertTrue(files)
        problems = [
            f"{path.relative_to(root)}: {problem}"
            for path in files
            for problem in forbidden_imports(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(problems, [])

    def test_boundary_detector_rejects_web_dependencies(self):
        self.assertTrue(forbidden_imports("from django.shortcuts import render\n"))
        self.assertTrue(forbidden_imports("from apps.office.views.home import home\n"))
        self.assertEqual(forbidden_imports("from dataclasses import dataclass\n"), [])
