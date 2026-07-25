from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _migration_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0053_shared_attendance_activities.py"
    )


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "shared_attendance_migration",
        _migration_path(),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {"alembic": SimpleNamespace(op=MagicMock())},
    ):
        spec.loader.exec_module(module)
    return module


def test_shared_attendance_migration_preserves_historical_scan_rows() -> None:
    source = _migration_path().read_text(encoding="utf-8")

    assert 'sa.Column("canonical_session_id", sa.UUID(), nullable=True)' in source
    assert "canonical_session_id = id" in source
    assert "SET canonical_session_id = ranked.canonical_id" in source
    assert "status = 'completed'" not in source
    assert "id = canonical_session_id" in source
    assert "fk_attendance_sessions_canonical_session_id" in source
    assert "DELETE FROM attendance_records" not in source
    assert "UPDATE attendance_records" not in source
    assert "DELETE FROM attendance_sessions" not in source
    assert "uq_attendance_sessions_active_group_name" in source
    assert (
        "status IN ('draft', 'active') AND id = canonical_session_id"
        in source
    )
    assert 'op.drop_column("attendance_sessions", "canonical_session_id")' in source


def test_upgrade_uses_postgresql_safe_whitespace_normalization() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()

    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    normalization_sql = operation_proxy.execute.call_args_list[0].args[0]
    assert (
        "regexp_replace(btrim(name), '[[:space:]]+', ' ', 'g')"
        in normalization_sql
    )
    assert "E'" not in normalization_sql
    assert "\\" not in normalization_sql
