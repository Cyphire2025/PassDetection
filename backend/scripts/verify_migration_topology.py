"""Fail CI when Alembic no longer has one reviewed deployable head."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

EXPECTED_HEAD = "0090_upload_configuration"
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
        raise RuntimeError(
            f"Expected one Alembic head {EXPECTED_HEAD!r}; observed {heads!r}"
        )
    head = scripts.get_revision(EXPECTED_HEAD)
    if head.down_revision != SECURITY_REVISION:
        raise RuntimeError("Upload configuration must follow the security data migration")
    if scripts.get_revision(SECURITY_REVISION).down_revision != MERGE_REVISION:
        raise RuntimeError("The security data migration must follow the reviewed 0088 merge")
    merge = scripts.get_revision(MERGE_REVISION)
    raw_parents = merge.down_revision
    observed_parents = (
        {raw_parents}
        if isinstance(raw_parents, str)
        else set(raw_parents or ())
    )
    if observed_parents != EXPECTED_PARENTS:
        raise RuntimeError(
            "The reviewed 0088 merge parents changed: "
            f"expected {sorted(EXPECTED_PARENTS)!r}, "
            f"observed {sorted(observed_parents)!r}"
        )

    print(
        "Alembic topology verified: 0090 follows 0089 and the preserved 0088 merge "
        "of the My Photos and enterprise-hardening branches."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
