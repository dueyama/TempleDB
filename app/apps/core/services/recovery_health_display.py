"""Read the small recovery-monitor report without opening backup archives or the DB."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

from django.conf import settings

MAX_REPORT_BYTES = 16 * 1024
STALE_AFTER = timedelta(hours=2)
FUTURE_TOLERANCE = timedelta(minutes=5)
CHECK_LABELS = {
    "generation": "Piバックアップ作成",
    "receipt": "Mac受信",
    "verification": "保存済みバックアップ検査",
    "storage": "保存先・容量",
}


def _monitor_warning(message: str, checked_at: datetime | None = None) -> dict:
    return {
        "checked_at": checked_at,
        "checks": [{"label": "状態の確認", "message": message}],
    }


def _read_report(path: Path) -> dict:
    if not path.is_absolute():
        raise ValueError("The monitor report must use an absolute path.")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_REPORT_BYTES:
        raise ValueError("The monitor report must be a bounded regular file.")
    # O_NONBLOCK prevents an accidentally configured FIFO from hanging a home request.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size > MAX_REPORT_BYTES
            or (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino)
        ):
            raise ValueError("The monitor report must be a bounded regular file.")
        content = source.read(MAX_REPORT_BYTES + 1)
    if len(content) > MAX_REPORT_BYTES:
        raise ValueError("The monitor report is too large.")
    report = json.loads(content)
    if not isinstance(report, dict):
        raise ValueError("Invalid monitor report.")
    return report


def _validate_report(report: dict) -> tuple[datetime, list[dict]]:
    if (
        report.get("format") != "templedb-recovery-health"
        or type(report.get("version")) is not int
        or report["version"] != 1
        or report.get("status") not in {"ok", "warning", "unknown"}
    ):
        raise ValueError("Unsupported monitor report.")
    timestamp = report.get("checked_at")
    if not isinstance(timestamp, str):
        raise ValueError("Missing monitor timestamp.")
    checked_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("The monitor timestamp must include a timezone.")
    checked_at = checked_at.astimezone(UTC)
    checks = report.get("checks")
    if not isinstance(checks, list) or len(checks) != len(CHECK_LABELS):
        raise ValueError("Incomplete monitor report.")
    seen = set()
    display_checks = []
    statuses = set()
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("Invalid monitor check.")
        key = check.get("key")
        status = check.get("status")
        message = check.get("message")
        if (
            not isinstance(key, str)
            or key not in CHECK_LABELS
            or key in seen
            or not isinstance(status, str)
            or status not in {"ok", "pending", "warning", "unknown"}
            or not isinstance(message, str)
            or not message.strip()
            or len(message) > 240
            or any(ord(character) < 32 for character in message)
        ):
            raise ValueError("Invalid monitor check content.")
        seen.add(key)
        statuses.add(status)
        if status in {"warning", "unknown"}:
            display_checks.append({"label": CHECK_LABELS[key], "message": message})
    expected_status = (
        "warning" if "warning" in statuses else "unknown" if "unknown" in statuses else "ok"
    )
    if report["status"] != expected_status:
        raise ValueError("Inconsistent monitor status.")
    return checked_at, display_checks


def get_recovery_health_warning(*, path=None, now: datetime | None = None) -> dict | None:
    """Return home warning content; an empty setting explicitly disables this display."""
    configured_path = settings.TEMPLEDB_RECOVERY_HEALTH_PATH if path is None else path
    if not configured_path:
        return None
    try:
        checked_at, checks = _validate_report(_read_report(Path(configured_path)))
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        return _monitor_warning("バックアップの確認結果を読み取れません。状態を確認してください。")
    now = now or datetime.now(UTC)
    if checked_at > now + FUTURE_TOLERANCE:
        return _monitor_warning("確認結果の日時が未来になっています。機器の時刻を確認してください。")
    if now - checked_at > STALE_AFTER:
        return _monitor_warning(
            "確認結果が2時間以上更新されていません。Macの稼働状況と接続を確認してください。",
            checked_at,
        )
    return {"checked_at": checked_at, "checks": checks} if checks else None
