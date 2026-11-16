from __future__ import annotations

RETIRED_SET_ACTIVE_BATCH = "set_active_batch"
RETIRED_FOLLOW_LATEST_BATCH = "follow_latest_batch"

_RETIRED_OPERATION_LABELS = {
    RETIRED_SET_ACTIVE_BATCH: "表示 batch 切替",
    RETIRED_FOLLOW_LATEST_BATCH: "最新成功 batch 追従",
}


def source_operation_kind_label(operation_kind: str, default_label: str) -> str:
    return _RETIRED_OPERATION_LABELS.get(operation_kind, default_label)
