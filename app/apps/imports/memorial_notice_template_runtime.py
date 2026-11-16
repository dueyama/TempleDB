from __future__ import annotations

from django.db.utils import OperationalError, ProgrammingError

from apps.core.services import memorial_dates
from apps.core.services import temple_identity as temple_identity_services
from apps.core.services import tenant_policy as tenant_policy_services

from .models import MemorialNoticeTemplate


def _runtime_module():
    from . import memorial_notice_runtime

    return memorial_notice_runtime


def _hardcoded_memorial_notice_defaults() -> dict[str, str]:
    runtime = _runtime_module()
    return {
        "intro_text": runtime.DEFAULT_MEMORIAL_NOTICE_INTRO_TEMPLATE,
        "outro_text": runtime.DEFAULT_MEMORIAL_NOTICE_OUTRO_TEXT,
        "signature_text": runtime.DEFAULT_MEMORIAL_NOTICE_SIGNATURE_TEXT,
    }


def _effective_memorial_notice_defaults() -> dict[str, str]:
    return tenant_policy_services.get_memorial_notice_defaults(
        fallback_defaults=_hardcoded_memorial_notice_defaults(),
    )


def _get_saved_memorial_notice_template(source_id: str, target_year: int) -> MemorialNoticeTemplate | None:
    try:
        return (
            MemorialNoticeTemplate.objects.select_related("source")
            .filter(source__source_id=source_id, target_year=target_year)
            .first()
        )
    except (OperationalError, ProgrammingError):
        return None


def _resolve_memorial_notice_style_value(
    request_value: float | None,
    template_value: float | None,
    default_value: float,
) -> float:
    if request_value is not None:
        return request_value
    if template_value is not None:
        return template_value
    return default_value


def _memorial_notice_template_values(target_year: int, target_year_with_wareki: str) -> dict[str, str]:
    wareki_year = memorial_dates._to_wareki_year_numeric(target_year)
    return {
        "{{YEAR}}": str(target_year),
        "{{WAREKI_YEAR}}": wareki_year,
        "{{YEAR_LABEL}}": target_year_with_wareki,
        **temple_identity_services.memorial_notice_identity_tokens(),
    }


def _render_memorial_notice_template_text(text: str, replacements: dict[str, str]) -> str:
    rendered = text
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    return rendered


def _memorial_notice_template_token_rows(replacements: dict[str, str]) -> list[dict[str, str]]:
    runtime = _runtime_module()
    return [
        {
            **token_info,
            "example_label": replacements.get(token_info["token"], ""),
        }
        for token_info in runtime.MEMORIAL_NOTICE_TEMPLATE_TOKENS
    ]
