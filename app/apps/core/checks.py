from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, Warning, register
from django.db import DatabaseError, connection

from .models import DatabaseRuntimeIdentity
from .services import runtime_identity_guard, tenant_policy


@register()
def postgresql_demo_runtime_identity_checks(app_configs, **kwargs):
    del app_configs, kwargs
    if not getattr(settings, "TEMPLEDB_POSTGRESQL_DEMO_MODE", False):
        return []
    try:
        table_names = set(connection.introspection.table_names())
    except DatabaseError:
        return [
            Error(
                "PostgreSQLデモDBへ接続できず、runtime identityを確認できません。",
                id="core.E015",
            )
        ]
    if DatabaseRuntimeIdentity._meta.db_table not in table_names:
        return []
    try:
        runtime_identity_guard.assert_web_runtime_identity()
    except runtime_identity_guard.RuntimeIdentityGuardError as exc:
        return [Error(str(exc), id="core.E015")]
    return []


@register()
def tenant_policy_configuration_checks(app_configs, **kwargs):
    del app_configs, kwargs
    warnings = []
    try:
        tenant_policy.load_memorial_rules()
    except tenant_policy.TenantPolicyError as exc:
        message = str(exc)
        warning_id = "core.W001" if "policy file is missing:" in message else "core.W002"
        warnings.append(
            Warning(
                f"tenant policy memorial rules を確認してください: {message}",
                hint=(
                    "config/tenant_policy/default/memorial_rules.json を整備してください。"
                    " 通常 runtime は policy file を優先し、未整備時だけ hardcoded fallback を使います。"
                ),
                id=warning_id,
            )
        )
    try:
        tenant_policy.load_labels()
    except tenant_policy.TenantPolicyError as exc:
        message = str(exc)
        warning_id = "core.W003" if "policy file is missing:" in message else "core.W004"
        warnings.append(
            Warning(
                f"tenant policy labels を確認してください: {message}",
                hint=(
                    "config/tenant_policy/default/labels.json を整備してください。"
                    " deceased field、帳票見出し、役職 roster/print の表示名は policy file を優先し、未整備時だけ hardcoded default を使います。"
                ),
                id=warning_id,
            )
        )
    try:
        tenant_policy.load_memorial_notice_defaults()
    except tenant_policy.TenantPolicyError as exc:
        message = str(exc)
        warning_id = "core.W005" if "policy file is missing:" in message else "core.W006"
        warnings.append(
            Warning(
                f"tenant policy memorial notice defaults を確認してください: {message}",
                hint=(
                    "config/tenant_policy/default/memorial_notice_defaults.json を整備してください。"
                    " 共通既定文面は policy file を優先し、未整備時だけ hardcoded fallback を使います。"
                ),
                id=warning_id,
            )
        )
    try:
        tenant_policy.load_terminology()
    except tenant_policy.TenantPolicyError as exc:
        message = str(exc)
        warning_id = "core.W007" if "policy file is missing:" in message else "core.W008"
        warnings.append(
            Warning(
                f"tenant policy terminology を確認してください: {message}",
                hint=(
                    "config/tenant_policy/default/terminology.json を整備してください。"
                    " 検索説明文、placeholder、analysis copy、AI query alias は"
                    " terminology policy を優先し、未整備時だけ hardcoded default を使います。"
                ),
                id=warning_id,
            )
        )
    try:
        tenant_policy.load_map_links()
    except tenant_policy.TenantPolicyError as exc:
        message = str(exc)
        warning_id = "core.W009" if "policy file is missing:" in message else "core.W010"
        warnings.append(
            Warning(
                f"tenant policy map links を確認してください: {message}",
                hint=(
                    "config/tenant_policy/default/map_links.json を整備してください。"
                    " household browser の住所リンク query 補正は policy file を優先し、"
                    "未整備時だけ hardcoded default を使います。"
                ),
                id=warning_id,
            )
        )
    try:
        tenant_policy.load_service_schedule_categories()
    except tenant_policy.TenantPolicyError as exc:
        message = str(exc)
        warning_id = "core.W011" if "policy file is missing:" in message else "core.W012"
        warnings.append(
            Warning(
                f"tenant policy service schedule categories を確認してください: {message}",
                hint=(
                    "config/tenant_policy/default/service_schedule_categories.json を整備してください。"
                    " 現行 ServiceSchedule.category の表示名と並び順は policy file を優先し、"
                    "未整備時だけ hardcoded default を使います。"
                ),
                id=warning_id,
            )
        )
    try:
        tenant_policy.load_relationship_labels()
    except tenant_policy.TenantPolicyError as exc:
        message = str(exc)
        warning_id = "core.W013" if "policy file is missing:" in message else "core.W014"
        warnings.append(
            Warning(
                f"tenant policy relationship labels を確認してください: {message}",
                hint=(
                    "config/tenant_policy/default/relationship_labels.json を整備してください。"
                    " 人物編集の続柄候補は policy file を優先し、"
                    "未整備時だけ hardcoded default を使います。"
                ),
                id=warning_id,
            )
        )
    return warnings
