"""Submit a browser exit request for this disposable preview only."""
from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
import time
from pathlib import Path

from config.realdata_preview_guard import load_preview_record


def _private_json(path: Path) -> dict:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.getuid() or info.st_mode & 0o077
            or info.st_size > 65536):
        raise ValueError("テスト環境の操作記録が不正です。")
    return json.loads(path.read_text())


def request_exit(*, action: str, run_id: str) -> None:
    if action not in {"finish", "stop"}:
        raise ValueError("終了操作を選んでください。")
    record = load_preview_record()
    session = Path(record["session_dir"])
    owner = _private_json(session / "owner.json")
    if owner != {"format": record["format"], "run_id": run_id,
                 "source_root": record["source_root"]} or session.name != "preview-" + run_id:
        raise ValueError("この画面は現在のテスト環境と一致しません。")
    state_root = Path(record["source_root"]) / "instances/realdata-preview"
    if state_root.resolve() != state_root:
        raise ValueError("テスト環境の保存先が一致しません。")
    state = _private_json(state_root / "status.json")
    if (state.get("phase") != "ready" or state.get("run_id") != run_id
            or state.get("session_dir") != str(session)):
        raise ValueError("このテスト環境は終了操作を受け付けられません。")
    request_path = session / "control-request.json"
    payload = {"run_id": run_id, "action": action, "not_before": time.time() + 3}
    # Serialize browser submissions and rename a complete file; the worker never
    # sees partial JSON or a transient hard link, and the first choice wins.
    lock_path = session / "control.lock"
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if request_path.exists() or request_path.is_symlink():
            previous = _private_json(request_path)
            if previous.get("run_id") != run_id or previous.get("action") != action:
                raise ValueError("すでに別の終了操作を受け付けています。")
            return
        fd, temporary = tempfile.mkstemp(prefix=".control-", dir=session)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(payload, handle)
            os.replace(temporary, request_path)
        finally:
            Path(temporary).unlink(missing_ok=True)
