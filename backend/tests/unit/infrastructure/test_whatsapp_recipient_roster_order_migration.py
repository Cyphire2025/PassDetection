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
        / "0050_whatsapp_recipient_roster_order.py"
    )
    spec = importlib.util.spec_from_file_location(
        "whatsapp_recipient_roster_order_migration",
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


def test_roster_order_migration_is_additive_and_follows_current_head() -> None:
    migration = _load_migration()

    assert migration.revision == "0050_whatsapp_roster_order"
    assert migration.down_revision == "0049_visa_ai_image_jobs"

    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    assert operation_proxy.add_column.call_count == 2
    assert operation_proxy.execute.call_count == 2
    assert operation_proxy.create_index.call_count == 2
    sql = "\n".join(
        str(call.args[0])
        for call in operation_proxy.execute.call_args_list
    )
    assert "ROW_NUMBER() OVER" in sql
    assert "whatsapp_broadcast_recipients" in sql
    assert "whatsapp_broadcast_rejected_contacts" in sql
    assert "DELETE" not in sql.upper()


def test_roster_order_migration_is_reversible() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()

    with patch.object(migration, "op", operation_proxy):
        migration.downgrade()

    assert operation_proxy.drop_index.call_count == 2
    assert operation_proxy.drop_column.call_count == 2
