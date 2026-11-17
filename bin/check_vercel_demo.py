"""Exercise the synthetic preview in an isolated Python process, including writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch


def exercise(workspace: Path) -> dict:
    sys.path[:0] = [str(workspace), str(workspace / "app")]
    from http.cookies import SimpleCookie

    import django
    from django.test import RequestFactory
    from vercel_demo import runtime
    from vercel_demo.wsgi import COOKIE, SIGNER, application

    factory = RequestFactory()
    assert (5, 2, 19) <= django.VERSION[:3] < (5, 3, 0), django.get_version()
    seed = workspace / "demo_seed/data/runtime/demo.sqlite3"
    seed_hash = hashlib.sha256(seed.read_bytes()).hexdigest()

    def request(jar, path, data=None):
        cookie = "; ".join(f"{key}={value.value}" for key, value in jar.items())
        kwargs = {"secure": True, "HTTP_COOKIE": cookie, "HTTP_REFERER": "https://testserver" + path}
        generated = factory.get(path, **kwargs) if data is None else factory.post(path, data, **kwargs)
        result = {}

        def respond(status, headers, exc_info=None):
            result.update(status=int(status.split()[0]), headers=dict(headers))
            for name, value in headers:
                if name.lower() == "set-cookie":
                    jar.load(value)

        result["body"] = b"".join(application(generated.environ, respond)).decode()
        return result

    from apps.imports.models import (
        AnnualMembershipFeePayment,
        AnnualMembershipFeeSetting,
        DeceasedProfile,
        ImportBatch,
        OfferingPayment,
        ServiceSchedule,
        VisitNote,
    )

    dataset = workspace / "datasets/synthetic_demo_v1"

    def check_dates(started_on):
        def load(name):
            return json.loads((dataset / (name + ".json")).read_text())

        def day(row, explicit, offset, *, fallback=None):
            if row.get(explicit):
                return date.fromisoformat(row[explicit])
            if row.get(offset) not in (None, ""):
                return started_on + timedelta(days=int(row[offset]))
            return fallback

        schedules = load("service_schedules")
        expected = {row["schedule_id"]: (
            day(row, "target_date", "target_offset_days"),
            day(row, "scheduled_date", "scheduled_offset_days"),
        ) for row in schedules}
        actual = {uid: (target, scheduled) for uid, target, scheduled in ServiceSchedule.objects.values_list(
            "schedule_uid", "target_date", "scheduled_date",
        )}
        assert actual == expected
        assert ServiceSchedule.objects.filter(
            scheduled_date__gte=started_on, scheduled_date__lte=started_on + timedelta(days=7),
        ).exists()
        for name, model, field, offset in (
            ("offering_payments", OfferingPayment, "received_on", "received_offset_days"),
            ("visit_notes", VisitNote, "visited_on", "visited_offset_days"),
        ):
            assert sorted(model.objects.values_list(field, flat=True)) == sorted(
                day(row, field, offset, fallback=started_on) for row in load(name)
            )
        fees = load("membership_fees")
        def year(row):
            return int(row.get("year") or started_on.year + int(row.get("year_offset") or 0))

        assert sorted(AnnualMembershipFeeSetting.objects.values_list("year", flat=True)) == sorted(
            year(row) for row in fees["settings"]
        )
        assert sorted(AnnualMembershipFeePayment.objects.values_list("year", "received_on")) == sorted(
            (year(row), day(row, "received_on", "received_offset_days", fallback=started_on))
            for row in fees["payments"]
        )
        # Explicit historical dates retain their original meaning.
        assert sorted(DeceasedProfile.objects.values_list("death_date", flat=True)) == sorted(
            day(row, "death_date", "death_offset_days") for row in load("memorials")
        )

    # The same built artifact must start fresh trials years later, across New Year
    # and on leap day, without shifting an existing trial's dates.
    dated = SimpleCookie()
    with patch("django.utils.timezone.localdate", return_value=date(2031, 12, 31)):
        assert request(dated, "/login/")["status"] == 200
        check_dates(date(2031, 12, 31))
        batch_id = ImportBatch.objects.get().pk
    with patch("django.utils.timezone.localdate", return_value=date(2032, 1, 1)):
        assert request(dated, "/login/")["status"] == 200
        check_dates(date(2031, 12, 31))
        assert ImportBatch.objects.get().pk == batch_id
        response = request(dated, "/logout/", {"csrfmiddlewaretoken": dated["csrftoken"].value})
        assert response["status"] == 302
        assert request(dated, "/login/")["status"] == 200
        check_dates(date(2032, 1, 1))
        assert request(dated, "/logout/", {"csrfmiddlewaretoken": dated["csrftoken"].value})["status"] == 302
    with patch("django.utils.timezone.localdate", return_value=date(2032, 2, 29)):
        assert request(dated, "/login/")["status"] == 200
        check_dates(date(2032, 2, 29))
        assert request(dated, "/logout/", {"csrfmiddlewaretoken": dated["csrftoken"].value})["status"] == 302

    browsers = [SimpleCookie(), SimpleCookie()]
    for jar in browsers:
        response = request(jar, "/login/")
        assert response["status"] == 200, response["status"]
        assert "架空データだけの試用デモ" in response["body"]
        response = request(jar, "/login/", {"username": "demo", "password": "demo", "csrfmiddlewaretoken": jar["csrftoken"].value})
        assert response["status"] == 302, response["body"][-2000:]
        assert request(jar, "/")["status"] == 200
        assert request(jar, "/households/")["status"] == 200

    from apps.imports.forms import HouseholdEditForm
    from apps.imports.models import Household, RecordEditLog

    request(browsers[0], "/households/")
    household = Household.objects.order_by("household_uid").first()
    path = f"/households/{household.household_uid}/edit/"
    assert request(browsers[0], path)["status"] == 200
    form = HouseholdEditForm(instance=household)
    data = {key: form[key].value() or "" for key in form.fields}
    data.update(notes="Vercel架空デモの保存・隔離試験", change_note="架空コピーだけでの検証", csrfmiddlewaretoken=browsers[0]["csrftoken"].value)
    audit_before = RecordEditLog.objects.count()
    response = request(browsers[0], path, data)
    assert response["status"] == 302, response["body"][-4000:]
    assert "Vercel架空デモの保存・隔離試験" in request(browsers[0], path)["body"]
    assert RecordEditLog.objects.count() > audit_before
    with patch("django.utils.timezone.localdate", return_value=date(2033, 1, 1)):
        assert "Vercel架空デモの保存・隔離試験" in request(browsers[0], path)["body"]
    assert "Vercel架空デモの保存・隔離試験" not in request(browsers[1], path)["body"]
    before_failure = set(runtime.state_root().iterdir())
    with patch("vercel_demo.wsgi.call_command", side_effect=RuntimeError("synthetic init failure")):
        try:
            request(SimpleCookie(), "/login/")
        except RuntimeError as exc:
            assert str(exc) == "synthetic init failure"
        else:
            raise AssertionError("Initialization failure was swallowed")
    assert set(runtime.state_root().iterdir()) == before_failure
    assert request(browsers[1], "/")["status"] == 200
    first = runtime.state_root() / SIGNER.unsign(browsers[0][COOKIE].value)
    second = runtime.state_root() / SIGNER.unsign(browsers[1][COOKIE].value)
    assert first.is_dir() and second.is_dir()
    # At capacity, refuse a new visitor without resetting either existing visitor.
    maximum = runtime.MAX_SANDBOXES
    runtime.MAX_SANDBOXES = 2
    visitor = SimpleCookie()
    assert request(visitor, "/login/")["status"] == 503
    assert first.is_dir() and second.is_dir()
    assert request(browsers[1], "/")["status"] == 200
    # Logout closes SQLite and physically removes only that browser's copy.
    response = request(browsers[0], "/logout/", {"csrfmiddlewaretoken": browsers[0]["csrftoken"].value})
    assert response["status"] == 302
    assert browsers[0]["templedb_demo_sandbox"]["max-age"] == "0"
    assert not first.exists()
    assert second.is_dir()
    assert request(browsers[1], "/")["status"] == 200
    assert request(browsers[0], "/")["status"] == 302
    request(browsers[0], "/login/")
    response = request(browsers[0], "/login/", {"username": "demo", "password": "demo", "csrfmiddlewaretoken": browsers[0]["csrftoken"].value})
    assert response["status"] == 302
    assert "Vercel架空デモの保存・隔離試験" not in request(browsers[0], path)["body"]
    runtime.MAX_SANDBOXES = maximum
    # A four-hour-idle copy is reclaimed on the next request; active copies remain.
    idle = runtime.state_root() / SIGNER.unsign(browsers[0][COOKIE].value)
    os.utime(idle / ".last_used", (time.time() - runtime.SANDBOX_TTL - 1,) * 2)
    assert request(browsers[1], "/")["status"] == 200
    assert not idle.exists() and second.is_dir()
    assert request(visitor, "/login/")["status"] == 200
    # Byte admission limit also preserves existing sessions and the original seed.
    size_limit = runtime.MAX_STATE_BYTES
    runtime.MAX_STATE_BYTES = runtime.tree_bytes(runtime.state_root())
    assert request(SimpleCookie(), "/login/")["status"] == 503
    assert request(browsers[1], "/")["status"] == 200
    runtime.MAX_STATE_BYTES = size_limit
    assert hashlib.sha256(seed.read_bytes()).hexdigest() == seed_hash
    return {
        "django_version": django.get_version(),
        "trial_start_dates_year_rollover_leap_day": "passed",
        "existing_trial_edits_preserved_and_failed_init_removed": "passed",
        "login_home_households": "two browsers passed", "edit_save_and_audit": "passed",
        "browser_database_isolation": "passed", "logout_reset_and_other_browser_preserved": "passed",
        "logout_copy_removed_idle_reclaimed_capacity_preserved": "passed",
        "seed_sha256_unchanged": seed_hash,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(exercise(args.workspace.resolve()), ensure_ascii=False, indent=2))
        return
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("DJANGO_", "TEMPLEDB_", "DATABASE_", "GOOGLE_", "OPENAI_"))}
    environment.update(DJANGO_SETTINGS_MODULE="vercel_demo.settings", DJANGO_SECRET_KEY=secrets.token_urlsafe(48),
                       TEMPLEDB_VERCEL_STATE_ROOT=str(args.workspace.resolve().parent / ("check-" + secrets.token_hex(6))))
    subprocess.run([sys.executable, __file__, str(args.workspace.resolve()), "--worker"], env=environment, check=True)


if __name__ == "__main__":
    main()
