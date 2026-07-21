from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _load_migration():
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0043_rejected_imported_fields.py"
    )
    spec = importlib.util.spec_from_file_location(
        "whatsapp_rejected_imported_fields_migration",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {"alembic": SimpleNamespace(op=MagicMock())},
    ):
        spec.loader.exec_module(module)
    return module


def test_rejected_imported_fields_migration_follows_current_head() -> None:
    migration = _load_migration()
    assert migration.revision == "0043_rejected_imported_fields"
    assert migration.down_revision == "0042_whatsapp_rejected_contacts"


def test_rejected_imported_fields_migration_is_reversible() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()
    operation_proxy.add_column.assert_called_once()

    operation_proxy.reset_mock()
    with patch.object(migration, "op", operation_proxy):
        migration.downgrade()
    operation_proxy.drop_column.assert_called_once_with(
        "whatsapp_broadcast_rejected_contacts",
        "imported_fields",
    )
