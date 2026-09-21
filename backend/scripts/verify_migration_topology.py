"""Fail CI when Alembic no longer has one reviewed deployable head."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

EXPECTED_HEAD = "0105_whatsapp_phone_overrides"
UPLOAD_CONFIGURATION_REVISION = "0090_upload_configuration"
SECURITY_REVISION = "0089_revoke_legacy_refresh"
MERGE_REVISION = "0088_merge_my_photos_hardening"
EXPECTED_PARENTS = {
    "0086_my_photos_foundation",
    "0087_enterprise_hardening",
}


def main() -> int:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    heads = tuple(scripts.get_heads())
    if heads != (EXPECTED_HEAD,):
        raise RuntimeError(f"Expected one Alembic head {EXPECTED_HEAD!r}; observed {heads!r}")
    head = scripts.get_revision(EXPECTED_HEAD)
    if head.down_revision != "0103_whatsapp_template_language":
        raise RuntimeError("WhatsApp source contacts must follow language snapshots")
    if scripts.get_revision("0103_whatsapp_template_language").down_revision != "0102_public_upload_contact_otp":
        raise RuntimeError("WhatsApp language snapshots must follow public contact OTP")
    if scripts.get_revision("0102_public_upload_contact_otp").down_revision != "0101_client_group_import_only":
        raise RuntimeError("Public contact OTP must follow import-only groups")
    if scripts.get_revision("0101_client_group_import_only").down_revision != "0100_whatsapp_group_archive":
        raise RuntimeError("Import-only groups must follow WhatsApp broadcast archives")
    if scripts.get_revision("0100_whatsapp_group_archive").down_revision != "0099_gc_group_access_removal":
        raise RuntimeError("WhatsApp broadcast archives must follow GC App group removal")
    if scripts.get_revision("0099_gc_group_access_removal").down_revision != "0098_notification_saved_delete":
        raise RuntimeError("GC App group removal must follow saved notification deletion")
    if scripts.get_revision("0098_notification_saved_delete").down_revision != "0097_authored_notifications":
        raise RuntimeError("Saved notification deletion must follow authored notifications")
    if scripts.get_revision("0097_authored_notifications").down_revision != "0096_mobile_phone_lookup":
        raise RuntimeError("Authored notifications must follow submitted phone lookup")
    if scripts.get_revision("0096_mobile_phone_lookup").down_revision != "0095_mobile_fcm_delivery":
        raise RuntimeError("Submitted phone lookup must follow FCM delivery states")
    if scripts.get_revision("0095_mobile_fcm_delivery").down_revision != "0094_whatsapp_receipt_inbox":
        raise RuntimeError("FCM delivery states must follow the durable WhatsApp receipt inbox")
    if scripts.get_revision("0094_whatsapp_receipt_inbox").down_revision != "0093_phone_welcome":
        raise RuntimeError("The durable WhatsApp receipt inbox must follow phone welcome prerequisites")
    phone_welcome = scripts.get_revision("0093_phone_welcome")
    if phone_welcome.down_revision != "0092_whatsapp_matching_fields":
        raise RuntimeError("Phone welcome prerequisites must follow WhatsApp matching fields")
    matching = scripts.get_revision("0092_whatsapp_matching_fields")
    if matching.down_revision != "0091_qualifier_other_relation":
        raise RuntimeError("WhatsApp matching fields must follow qualifier relationships")
    qualifier = scripts.get_revision("0091_qualifier_other_relation")
    if qualifier.down_revision != UPLOAD_CONFIGURATION_REVISION:
        raise RuntimeError("Custom qualifier relationships must follow upload configuration")
    if scripts.get_revision(UPLOAD_CONFIGURATION_REVISION).down_revision != SECURITY_REVISION:
        raise RuntimeError("Upload configuration must follow the security data migration")
    if scripts.get_revision(SECURITY_REVISION).down_revision != MERGE_REVISION:
        raise RuntimeError("The security data migration must follow the reviewed 0088 merge")
    merge = scripts.get_revision(MERGE_REVISION)
    raw_parents = merge.down_revision
    observed_parents = {raw_parents} if isinstance(raw_parents, str) else set(raw_parents or ())
    if observed_parents != EXPECTED_PARENTS:
        raise RuntimeError(
            "The reviewed 0088 merge parents changed: "
            f"expected {sorted(EXPECTED_PARENTS)!r}, "
            f"observed {sorted(observed_parents)!r}"
        )

    print(
        "Alembic topology verified: 0104 follows 0103, 0102, 0101, 0100, 0099, 0098, 0097, 0096, 0095, 0094, 0093, 0092, 0091, 0090, 0089 and the preserved 0088 merge "
        "of the My Photos and enterprise-hardening branches."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
