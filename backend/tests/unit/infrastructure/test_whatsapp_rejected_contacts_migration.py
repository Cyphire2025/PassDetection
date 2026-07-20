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
        / "0042_whatsapp_rejected_contacts.py"
    )
    spec = importlib.util.spec_from_file_location(
        "whatsapp_rejected_contacts_migration",
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


def test_rejected_contacts_migration_follows_current_head() -> None:
    migration = _load_migration()
    assert migration.revision == "0042_whatsapp_rejected_contacts"
    assert migration.down_revision == "0041_global_connects_brand"


def test_rejected_contacts_migration_is_reversible() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()
    operation_proxy.create_table.assert_called_once()
    assert operation_proxy.create_index.call_count == 2

    operation_proxy.reset_mock()
    with patch.object(migration, "op", operation_proxy):
        migration.downgrade()
    operation_proxy.drop_table.assert_called_once_with(
        "whatsapp_broadcast_rejected_contacts"
    )
