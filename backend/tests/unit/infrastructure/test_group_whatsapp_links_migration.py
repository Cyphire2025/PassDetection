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
        / "0039_group_whatsapp_broadcast_links.py"
    )
    spec = importlib.util.spec_from_file_location(
        "group_whatsapp_links_migration", migration_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules, {"alembic": SimpleNamespace(op=MagicMock())}
    ):
        spec.loader.exec_module(module)
    return module


def test_group_whatsapp_link_migration_follows_current_head() -> None:
    migration = _load_migration()
    assert migration.revision == "0039_group_whatsapp_links"
    assert migration.down_revision == "0038_whatsapp_resend"


def test_group_whatsapp_link_migration_is_reversible() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()
    operation_proxy.create_table.assert_called_once()
    assert operation_proxy.create_index.call_count == 5

    operation_proxy.reset_mock()
    with patch.object(migration, "op", operation_proxy):
        migration.downgrade()
    operation_proxy.drop_table.assert_called_once_with(
        "client_group_whatsapp_broadcast_links"
    )
