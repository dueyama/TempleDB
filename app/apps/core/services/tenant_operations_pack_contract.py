from __future__ import annotations

from pathlib import Path

PACKAGE_KIND = "templedb-tenant-operations-pack-v1"
PACKAGE_VERSION = 1
PRIVACY_CLASSIFICATION = "restricted-tenant-operations"
OPERATIONS_MANIFEST_PATH = "MANIFEST.json"
VERIFICATION_SUMMARY_PATH = "verification/restore-summary.json"
SOURCE_ENV_PATH = "reference/source.env"
TENANT_POLICY_ARCHIVE_ROOT = Path("tenant_policy/default")
TENANT_PREFERENCES_ARCHIVE_ROOT = Path("tenant_preferences")
PRIVATE_PAYLOAD_ARCHIVE_ROOT = Path("payload/data/private")
SOURCE_REGISTRY_ARCHIVE_PATH = Path("payload/data/runtime/source_registry.json")
GENERATED_REFERENCE_ARCHIVE_ROOT = Path("reference/data/generated")
README_PATH = "docs/README.md"
ARCHIVE_MANIFEST_PATH = "docs/archive_manifest.json"
ARCHIVE_CHECKSUMS_PATH = "docs/checksums.txt"

SAFETY_CONTRACT = {
    "demo_promotion": False,
    "fresh_product_target_required": True,
    "external_effects_must_remain_disabled": True,
    "primary_cutover_included": False,
}

__all__ = [
    "ARCHIVE_CHECKSUMS_PATH",
    "ARCHIVE_MANIFEST_PATH",
    "GENERATED_REFERENCE_ARCHIVE_ROOT",
    "OPERATIONS_MANIFEST_PATH",
    "PACKAGE_KIND",
    "PACKAGE_VERSION",
    "PRIVATE_PAYLOAD_ARCHIVE_ROOT",
    "PRIVACY_CLASSIFICATION",
    "README_PATH",
    "SAFETY_CONTRACT",
    "SOURCE_ENV_PATH",
    "SOURCE_REGISTRY_ARCHIVE_PATH",
    "TENANT_POLICY_ARCHIVE_ROOT",
    "TENANT_PREFERENCES_ARCHIVE_ROOT",
    "VERIFICATION_SUMMARY_PATH",
]
