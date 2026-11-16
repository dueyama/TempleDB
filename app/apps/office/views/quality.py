import csv
from io import StringIO
from urllib.parse import urlencode

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date

from apps.imports.data_science_csv_export import DEATH_DEMOGRAPHICS_CSV_COLUMNS
from apps.office import services
from apps.office.services import quality as quality_services
from apps.office.services.history import build_record_history_context
from apps.office.web_support import (
    _normalize_record_history_action,
    _normalized_request_url,
    _parse_boolean_flag,
)


def data_quality(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    context = services.build_data_quality_context(query=query)
    context.pop("selected_source_id", None)
    context["current_url"] = _normalized_request_url(request)
    return render(request, "office/data_quality.html", context)


def special_searches(request: HttpRequest) -> HttpResponse:
    search_key = request.GET.get("search")
    query = request.GET.get("q", "")
    context = services.build_special_search_context(search_key=search_key, query=query)
    context.pop("selected_source_id", None)
    context["current_url"] = _normalized_request_url(request)
    return render(request, "office/special_searches.html", context)


def data_science(request: HttpRequest) -> HttpResponse:
    if request.GET.get("_render") == "full":
        context = _build_data_science_context(request)
        context.update(
            {
                "analytics_base_template": "base.html",
                "analytics_deferred": False,
                "analytics_fragment_only": False,
                "analytics_full_render": True,
            }
        )
        return render(request, "office/data_science.html", context)

    full_query = request.GET.copy()
    full_query["_render"] = "full"
    full_url = reverse("office:data_science")
    if encoded_query := full_query.urlencode():
        full_url = f"{full_url}?{encoded_query}"

    return render(
        request,
        "office/data_science.html",
        {
            "analytics_base_template": "base.html",
            "analytics_deferred": True,
            "analytics_fragment_only": False,
            "analytics_full_render": False,
            "analytics_fragment_url": reverse("office:data_science_content"),
            "analytics_full_url": full_url,
            "current_url": _normalized_request_url(request),
        },
    )


def data_science_content(request: HttpRequest) -> HttpResponse:
    context = _build_data_science_context(request)
    context.update(
        {
            "analytics_base_template": "office/_data_science_fragment_base.html",
            "analytics_deferred": False,
            "analytics_fragment_only": True,
            "analytics_full_render": False,
        }
    )
    return render(request, "office/data_science.html", context)


def _build_data_science_context(request: HttpRequest) -> dict:
    month_cohort_mode = request.GET.get("month_cohort_mode")
    age_cohort_mode = request.GET.get("age_cohort_mode")
    context = services.build_data_science_context(
        month_cohort_mode=month_cohort_mode,
        age_cohort_mode=age_cohort_mode,
    )
    context.pop("selected_source_id", None)
    context["current_url"] = _normalized_request_url(request)
    return context


def death_demographics_csv(request: HttpRequest) -> HttpResponse:
    start_date, start_error = _parse_required_date(
        request.GET.get("start_date"),
        field_label="開始日",
    )
    end_date, end_error = _parse_required_date(
        request.GET.get("end_date"),
        field_label="終了日",
    )
    errors = [error for error in (start_error, end_error) if error]
    if start_date is not None and end_date is not None and start_date > end_date:
        errors.append("開始日は終了日以前にしてください。")
    if errors:
        return _plain_text_response(" / ".join(errors), status=400)

    payload = quality_services.build_death_demographics_csv_rows(
        start_date=start_date,
        end_date=end_date,
    )
    if not payload["available"]:
        return _plain_text_response(payload["message"], status=400)

    buffer = StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow(DEATH_DEMOGRAPHICS_CSV_COLUMNS)
    for row in payload["rows"]:
        writer.writerow(
            [row.get(column, "") for column in DEATH_DEMOGRAPHICS_CSV_COLUMNS]
        )

    response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    filename = f"death-demographics-{start_date:%Y%m%d}-{end_date:%Y%m%d}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def record_history(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    action = _normalize_record_history_action(request.GET.get("action"))
    context = build_record_history_context(
        query=query,
        action=action,
        current_url=_normalized_request_url(request),
    )
    context.pop("selected_source_id", None)
    return render(request, "office/record_history.html", context)


def universal_search(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        force = _parse_boolean_flag(request.POST.get("force"))
        include_history = _parse_boolean_flag(request.POST.get("history"))
        stats = services.sync_auto_memo_tags(include_history=include_history, force=force)
        mode_label = "AI+キーワード" if stats["ai_available"] else "キーワード"
        messages.success(
            request,
            (
                f"自動タグを更新しました。"
                f"{mode_label} / 対象 {stats['processed_count']}件 / 更新 {stats['updated_count']}件 / "
                f"残り {stats.get('remaining_count', 0)}件 / "
                f"新規タグ {stats['created_tag_count']}件 / 付与タグ {stats['assigned_tag_count']}件 / "
                f"スキップ {stats['skipped_count']}件 / "
                f"AI実行 {stats.get('ai_processed_count', 0)}件 / "
                f"AI残り {stats.get('ai_deferred_count', 0)}件"
            ),
        )
        return redirect(_universal_search_url(request))

    query = request.GET.get("q", "")
    selected_tag_slug = request.GET.get("tag", "")
    selected_note_type = request.GET.get("note_type", "")
    selected_result_kind = request.GET.get("kind", "")
    search_mode = request.GET.get("mode", "smart")
    include_history = _parse_boolean_flag(request.GET.get("history"))
    context = services.build_universal_search_context(
        query=query,
        selected_tag_slug=selected_tag_slug,
        selected_note_type=selected_note_type,
        selected_result_kind=selected_result_kind,
        search_mode=search_mode,
        include_history=include_history,
    )
    context.pop("selected_source_id", None)
    context["current_url"] = _normalized_request_url(request)
    return render(request, "office/universal_search.html", context)


def memo_tag_catalog(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    context = services.build_memo_tag_catalog_context(query=query)
    context.pop("selected_source_id", None)
    context["current_url"] = _normalized_request_url(request)
    return render(request, "office/memo_tag_catalog.html", context)


def _universal_search_url(request: HttpRequest) -> str:
    query = {}
    for key, post_key in (
        ("q", "q"),
        ("tag", "tag"),
        ("note_type", "note_type"),
        ("kind", "kind"),
        ("mode", "mode"),
        ("history", "history"),
    ):
        value = (request.POST.get(post_key) or "").strip()
        if value:
            query[key] = value
    url = reverse("office:universal_search")
    if not query:
        return url
    return f"{url}?{urlencode(query)}"


def _parse_required_date(value: str | None, *, field_label: str):
    raw_value = (value or "").strip()
    if not raw_value:
        return None, f"{field_label}を指定してください。"
    parsed = parse_date(raw_value)
    if parsed is None:
        return None, f"{field_label}は YYYY-MM-DD 形式で指定してください。"
    return parsed, ""


def _plain_text_response(message: str, *, status: int) -> HttpResponse:
    return HttpResponse(message, status=status, content_type="text/plain; charset=utf-8")
