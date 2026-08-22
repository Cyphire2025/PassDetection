from __future__ import annotations

import importlib.util
from pathlib import Path


def test_platform_retention_migration_is_linear_and_hold_aware() -> None:
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0085_platform_retention_controls.py"
    )
    source = migration_path.read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("migration_0085", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.down_revision == "0084_identity_lifecycle"
    assert "passport_purge_at" in source
    assert "passport_retention_days_applied" in source
    assert "passport_legal_hold_reason" in source
    assert "ck_client_groups_passport_legal_hold_shape" in source
    assert "ix_client_groups_passport_retention_due" in source
