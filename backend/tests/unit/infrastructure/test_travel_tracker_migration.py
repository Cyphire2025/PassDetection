"""Additive schema and history-preserving downgrade contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def migration():
    source = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "0129_travel_tracker.py"
    spec = importlib.util.spec_from_file_location("travel_tracker_migration", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_additive_scoped_table_preserves_existing_passport_schema(monkeypatch):
    module = migration()
    proxy = MagicMock()
    monkeypatch.setattr(module, "op", proxy)
    module.upgrade()
    assert module.revision == "0129_travel_tracker"
    assert module.down_revision == "0128_mcp_document_delivery"
    args = proxy.create_table.call_args.args
    assert args[0] == "travel_tracker"
    columns = {column.name: column for column in args[1:] if hasattr(column, "nullable")}
    assert columns["passenger_id"].primary_key
    assert not columns["visa_applied"].nullable and not columns["flight_booked"].nullable
    constraint = next(
        value
        for value in args[1:]
        if getattr(value, "name", None) == "fk_travel_tracker_passenger_scope"
    )
    assert constraint.column_keys == ["passenger_id", "agency_id", "group_id"]
    assert constraint.ondelete == "CASCADE"
    proxy.add_column.assert_not_called()
    proxy.drop_table.assert_not_called()


@pytest.mark.parametrize("has_history", [False, True])
def test_downgrade_refuses_to_drop_recorded_history(monkeypatch, has_history):
    module = migration()
    proxy = MagicMock()
    proxy.get_bind.return_value.execute.return_value.scalar_one.return_value = has_history
    monkeypatch.setattr(module, "op", proxy)
    if has_history:
        with pytest.raises(RuntimeError, match="preserve readiness history"):
            module.downgrade()
        proxy.drop_table.assert_not_called()
    else:
        module.downgrade()
        proxy.drop_table.assert_called_once_with("travel_tracker")
    assert any("ACCESS EXCLUSIVE" in str(call.args[0]) for call in proxy.execute.call_args_list)
