from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _load_migration():  # type: ignore[no-untyped-def]
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0078_client_manager_login.py"
    )
    spec = importlib.util.spec_from_file_location(
        "client_manager_login_migration",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"alembic": SimpleNamespace(op=MagicMock())}):
        spec.loader.exec_module(migration)
    return migration


def test_client_manager_login_migration_repairs_only_password_created_invites() -> None:
    migration = _load_migration()
    operations = MagicMock()
    migration.op = operations

    migration.upgrade()

    assert migration.revision == "0078_client_manager_login"
    assert migration.down_revision == "0077_gc_app_admin_list"
    assert operations.alter_column.call_args.kwargs["server_default"].text == "false"
    statement = str(operations.execute.call_args.args[0])
    assert "status = 'invited'" in statement
    assert "invitation_token_hash IS NULL" in statement
    assert "invitation_expires_at IS NULL" in statement
    assert "THEN 'active'" in statement
    assert "force_password_change = false" in statement
    assert "revision = revision + 1" in statement


def test_client_manager_login_migration_downgrade_preserves_repaired_accounts() -> None:
    migration = _load_migration()
    operations = MagicMock()
    migration.op = operations

    migration.downgrade()

    operations.execute.assert_not_called()
    assert operations.alter_column.call_args.kwargs["server_default"].text == "true"
