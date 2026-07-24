from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import sqlalchemy as sa


def _load_migration():
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0051_passport_exports_and_replacements.py"
    )
    spec = importlib.util.spec_from_file_location(
        "passport_exports_and_replacements_migration",
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


def _create_table_call(operation_proxy: MagicMock, table_name: str):
    return next(
        call for call in operation_proxy.create_table.call_args_list if call.args[0] == table_name
    )


def test_migration_follows_current_head_and_creates_both_audit_tables() -> None:
    migration = _load_migration()

    assert migration.revision == "0051_exports_replacements"
    assert migration.down_revision == "0050_whatsapp_roster_order"

    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    assert operation_proxy.create_table.call_count == 2
    export_call = _create_table_call(
        operation_proxy,
        "passport_export_history",
    )
    resolution_call = _create_table_call(
        operation_proxy,
        "passport_roster_resolutions",
    )
    export_columns = {
        item.name: item for item in export_call.args[1:] if isinstance(item, sa.Column)
    }
    resolution_columns = {
        item.name: item for item in resolution_call.args[1:] if isinstance(item, sa.Column)
    }

    assert {
        "snapshot_submission_ids",
        "exported_submission_ids",
        "exported_people_snapshot",
        "baseline_export_id",
        "request_id",
        "format_version",
        "status",
        "completed_at",
    }.issubset(export_columns)
    assert export_columns["snapshot_submission_ids"].nullable is False
    assert export_columns["exported_submission_ids"].nullable is False
    assert export_columns["exported_people_snapshot"].nullable is False
    assert export_columns["status"].nullable is False
    assert export_columns["completed_at"].nullable is True
    export_constraints = {
        item.name
        for item in export_call.args[1:]
        if isinstance(item, sa.CheckConstraint)
    }
    assert "ck_passport_export_history_completion" in export_constraints
    assert {
        "submission_id",
        "broadcast_recipient_id",
        "replaced_recipient_normalized_phone",
        "original_recipient_name",
        "original_recipient_phone",
        "original_recipient_imported_fields",
        "suppressed_recipient_ids",
        "excluded_submission_ids",
        "request_id",
        "status",
    }.issubset(resolution_columns)
    assert resolution_columns["suppressed_recipient_ids"].nullable is False
    assert resolution_columns["excluded_submission_ids"].nullable is False
    assert resolution_columns["original_recipient_imported_fields"].nullable is False

    operation_proxy.add_column.assert_called_once()
    added_table, added_column = operation_proxy.add_column.call_args.args
    assert added_table == "whatsapp_broadcast_recipients"
    assert added_column.name == "suppressed_by_roster_resolution_id"
    operation_proxy.create_foreign_key.assert_called_once_with(
        "fk_whatsapp_recipient_roster_resolution",
        "whatsapp_broadcast_recipients",
        "passport_roster_resolutions",
        ["suppressed_by_roster_resolution_id"],
        ["id"],
        ondelete="SET NULL",
    )


def test_migration_keeps_active_resolution_uniqueness_partial() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()

    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    index_calls = {call.args[0]: call for call in operation_proxy.create_index.call_args_list}
    active_submission = index_calls["uq_passport_roster_resolutions_active_submission"]
    active_recipient = index_calls["uq_passport_roster_resolutions_active_recipient"]
    assert active_submission.kwargs["unique"] is True
    assert str(active_submission.kwargs["postgresql_where"]) == "status = 'active'"
    assert active_recipient.kwargs["unique"] is True
    assert (
        str(active_recipient.kwargs["postgresql_where"])
        == "status = 'active' AND broadcast_recipient_id IS NOT NULL"
    )
    active_phone = index_calls["ix_passport_roster_resolutions_active_phone"]
    assert active_phone.kwargs.get("unique", False) is False
    assert str(active_phone.kwargs["postgresql_where"]) == (
        "status = 'active' AND resolution_type = 'replacement'"
    )
    assert "ix_whatsapp_broadcast_recipients_roster_resolution" in index_calls
    assert "ix_passport_export_history_group_kind_status_completed" in index_calls


def test_migration_downgrade_removes_recipient_fk_before_resolution_table() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()

    with patch.object(migration, "op", operation_proxy):
        migration.downgrade()

    method_calls = operation_proxy.method_calls
    drop_fk_position = next(
        index
        for index, call in enumerate(method_calls)
        if call[0] == "drop_constraint"
        and call.args[0] == "fk_whatsapp_recipient_roster_resolution"
    )
    drop_resolution_position = next(
        index
        for index, call in enumerate(method_calls)
        if call[0] == "drop_table" and call.args[0] == "passport_roster_resolutions"
    )
    assert drop_fk_position < drop_resolution_position
    assert operation_proxy.drop_column.call_args.args == (
        "whatsapp_broadcast_recipients",
        "suppressed_by_roster_resolution_id",
    )
    assert {call.args[0] for call in operation_proxy.drop_table.call_args_list} == {
        "passport_export_history",
        "passport_roster_resolutions",
    }
