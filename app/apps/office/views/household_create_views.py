from __future__ import annotations

from urllib.parse import urlparse

from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse, QueryDict
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.imports import canonical_population
from apps.imports.forms import NewHouseholdForm
from apps.imports.models import RecordEditLog
from apps.office.services.manual_household_creation import create_manual_household
from apps.office.services.record_history_mutations import _create_record_edit_log
from apps.office.services.record_history_snapshot import (
    _serialize_household_record,
    _serialize_person_record,
)
from apps.office.web_support import (
    _default_household_browser_url,
    _normalized_request_url,
    _request_actor_label,
    _resolve_next_url,
)

from .common import _ensure_source_record
from .household_transition_shared import _flash_record_action_message


def _household_browser_detail_return_url(next_url: str, household_id: str) -> str:
    browser_url = reverse("office:household_browser")
    parsed = urlparse(next_url or "")
    if parsed.path != browser_url:
        return _default_household_browser_url(household_id=household_id, focus="detail")
    query = QueryDict(parsed.query, mutable=True)
    for key in ("source_id", "backend"):
        query.pop(key, None)
    query["household_id"] = household_id
    query["focus"] = "detail"
    encoded = query.urlencode()
    return f"{browser_url}?{encoded}" if encoded else browser_url


def create_household(request: HttpRequest) -> HttpResponse:
    source_record = _ensure_source_record(None)
    batch = canonical_population.canonical_provenance_import_batch(
        source_id=source_record.source_id,
    )
    if batch is None:
        raise Http404("canonical provenance batch not found")
    next_url = _resolve_next_url(request, _default_household_browser_url())
    if request.method == "POST":
        form = NewHouseholdForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                household, head_person = create_manual_household(
                    batch=batch,
                    source_record=source_record,
                    form_data=form.cleaned_data,
                )
                household_log = _create_record_edit_log(
                    record_type=RecordEditLog.RecordType.HOUSEHOLD,
                    record=household,
                    before_data={},
                    after_data=_serialize_household_record(household),
                    editor_label=_request_actor_label(request),
                    change_note="戸主ブラウザで新しい家を作成",
                )
                person_log = _create_record_edit_log(
                    record_type=RecordEditLog.RecordType.PERSON,
                    record=head_person,
                    before_data={},
                    after_data=_serialize_person_record(head_person),
                    editor_label=_request_actor_label(request),
                    change_note="戸主ブラウザで新戸主を作成",
                )
            _flash_record_action_message(
                request,
                household_log,
                f"新しい家 {household.display_head_name()} を作成しました。",
            )
            _flash_record_action_message(
                request,
                person_log,
                f"{head_person.name} を戸主として作成しました。",
            )
            return redirect(
                _household_browser_detail_return_url(next_url, household.household_uid)
            )
    else:
        form = NewHouseholdForm(initial={"head_gender": "未決定"})

    return render(
        request,
        "office/new_household.html",
        {
            "title": "新しい家を作成",
            "next_url": next_url,
            "form": form,
            "current_url": _normalized_request_url(request),
        },
    )


__all__ = ["create_household"]
