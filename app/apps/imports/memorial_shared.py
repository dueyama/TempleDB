from __future__ import annotations

from apps.core.services import tenant_policy_memorial_notice as memorial_notice_policy
from apps.core.services.memorial_dates import (
    ERA_STARTS as ERA_STARTS,
)
from apps.core.services.memorial_dates import (
    KANJI_DIGITS as KANJI_DIGITS,
)
from apps.core.services.memorial_dates import (
    KIJITSU_STEPS as KIJITSU_STEPS,
)
from apps.core.services.memorial_dates import (
    MEMORIAL_RANKS as MEMORIAL_RANKS,
)
from apps.core.services.memorial_dates import (
    WEEKDAYS_JA as WEEKDAYS_JA,
)
from apps.core.services.memorial_dates import (
    _add_memorial_offset_years as _add_memorial_offset_years,
)
from apps.core.services.memorial_dates import (
    _add_memorial_years as _add_memorial_years,
)
from apps.core.services.memorial_dates import (
    _chunked as _chunked,
)
from apps.core.services.memorial_dates import (
    _effective_memorial_rules as _effective_memorial_rules,
)
from apps.core.services.memorial_dates import (
    _first_obon_date as _first_obon_date,
)
from apps.core.services.memorial_dates import (
    _format_month_day_kanji as _format_month_day_kanji,
)
from apps.core.services.memorial_dates import (
    _hardcoded_default_memorial_rules as _hardcoded_default_memorial_rules,
)
from apps.core.services.memorial_dates import (
    _kijitsu_offset_days_from_label as _kijitsu_offset_days_from_label,
)
from apps.core.services.memorial_dates import (
    _memorial_offset_years as _memorial_offset_years,
)
from apps.core.services.memorial_dates import (
    _memorial_offset_years_from_label as _memorial_offset_years_from_label,
)
from apps.core.services.memorial_dates import (
    _replace_year_clamped as _replace_year_clamped,
)
from apps.core.services.memorial_dates import (
    _to_kanji_number as _to_kanji_number,
)
from apps.core.services.memorial_dates import (
    _to_kanji_year_digits as _to_kanji_year_digits,
)
from apps.core.services.memorial_dates import (
    _to_memorial_label as _to_memorial_label,
)
from apps.core.services.memorial_dates import (
    _to_memorial_label_from_offset as _to_memorial_label_from_offset,
)
from apps.core.services.memorial_dates import (
    _to_wareki_date as _to_wareki_date,
)
from apps.core.services.memorial_dates import (
    _to_wareki_date_numeric as _to_wareki_date_numeric,
)
from apps.core.services.memorial_dates import (
    _to_wareki_year_numeric as _to_wareki_year_numeric,
)
from apps.core.services.memorial_dates import (
    _to_zenkaku_digits as _to_zenkaku_digits,
)

LEGACY_IMPORTED_SCHEDULE_SOURCE_TABLES = {
    "UTM010_予定明細",
    "UTY020_初盆予定作成",
}
MEMORIAL_NOTICE_ROWS_PER_PAGE = memorial_notice_policy.MEMORIAL_NOTICE_ROWS_PER_PAGE
DEFAULT_MEMORIAL_NOTICE_INTRO_TEXT = memorial_notice_policy.DEFAULT_MEMORIAL_NOTICE_INTRO_TEXT
DEFAULT_MEMORIAL_NOTICE_OUTRO_TEXT = memorial_notice_policy.DEFAULT_MEMORIAL_NOTICE_OUTRO_TEXT
DEFAULT_MEMORIAL_NOTICE_SIGNATURE_TEXT = memorial_notice_policy.DEFAULT_MEMORIAL_NOTICE_SIGNATURE_TEXT
DEFAULT_MEMORIAL_NOTICE_STYLE = memorial_notice_policy.DEFAULT_MEMORIAL_NOTICE_STYLE
