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
        / "0080_domestic_ticket_lanes.py"
    )
    spec = importlib.util.spec_from_file_location("domestic_ticket_lanes_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"alembic": SimpleNamespace(op=MagicMock())}):
        spec.loader.exec_module(migration)
    return migration


def test_upgrade_only_widens_the_distribution_receipt_constraint() -> None:
    migration = _load_migration()
    operations = MagicMock()
    migration.op = operations

    migration.upgrade()

    assert migration.revision == "0080_domestic_ticket_lanes"
    assert migration.down_revision == "0079_arrival_ticket_distribution"
    operations.drop_constraint.assert_called_once_with(
        "ck_document_upload_chunks_scope",
        "document_upload_chunks",
        type_="check",
    )
    condition = operations.create_check_constraint.call_args.args[2]
    assert "'flight_ticket_domestic'" in condition
    assert "'flight_ticket_domestic_arrival'" in condition
    operations.execute.assert_not_called()
    operations.delete.assert_not_called()


def test_downgrade_is_fail_closed_and_never_relabels_or_deletes_rows() -> None:
    migration = _load_migration()
    operations = MagicMock()
    migration.op = operations

    migration.downgrade()

    condition = operations.create_check_constraint.call_args.args[2]
    assert "flight_ticket_domestic" not in condition
    operations.execute.assert_not_called()
    operations.delete.assert_not_called()
