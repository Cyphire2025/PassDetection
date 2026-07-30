from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import sqlalchemy as sa

from app.infrastructure.database.email_models import Base


def _load_migration():
    migration_path = (
        Path(__file__).resolve().parents[3] / "alembic" / "versions" / "0061_email_integrations.py"
    )
    spec = importlib.util.spec_from_file_location(
        "email_integrations_migration",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"alembic": SimpleNamespace(op=MagicMock())}):
        spec.loader.exec_module(module)
    return module


def _table_call(operation_proxy: MagicMock, table_name: str):
    return next(
        call for call in operation_proxy.create_table.call_args_list if call.args[0] == table_name
    )


def test_email_migration_follows_current_head_and_creates_vertical_slice() -> None:
    migration = _load_migration()
    assert migration.revision == "0061_email_integrations"
    assert migration.down_revision == "0060_fine_rotation"

    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    assert [call.args[0] for call in operation_proxy.create_table.call_args_list] == [
        "email_connections",
        "email_oauth_states",
        "email_messages",
        "email_artifacts",
        "email_artifact_documents",
        "email_review_items",
        "email_activity_events",
    ]

    connection_call = _table_call(operation_proxy, "email_connections")
    connection_columns = {
        item.name: item for item in connection_call.args[1:] if isinstance(item, sa.Column)
    }
    assert connection_columns["access_token_ciphertext"].nullable is True
    assert connection_columns["refresh_token_ciphertext"].nullable is True
    assert isinstance(connection_columns["access_token_ciphertext"].type, sa.LargeBinary)
    assert "token_key_version" in connection_columns
    assert "sync_cursor" in connection_columns
    assert "sync_lease_expires_at" in connection_columns

    message_columns = {
        item.name: item
        for item in _table_call(operation_proxy, "email_messages").args[1:]
        if isinstance(item, sa.Column)
    }
    assert {
        "agency_id",
        "connection_id",
        "provider_message_id",
        "evidence_json",
        "artifact_count",
        "processed_artifact_count",
        "review_count",
    }.issubset(message_columns)


def test_email_migration_keeps_active_review_uniqueness_partial() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    index_calls = {call.args[0]: call for call in operation_proxy.create_index.call_args_list}
    message_index = index_calls["uq_email_review_items_active_message"]
    artifact_index = index_calls["uq_email_review_items_active_artifact"]
    assert message_index.kwargs["unique"] is True
    assert artifact_index.kwargs["unique"] is True
    assert str(message_index.kwargs["postgresql_where"]) == (
        "artifact_id IS NULL AND status IN ('open', 'deferred')"
    )
    assert str(artifact_index.kwargs["postgresql_where"]) == (
        "artifact_id IS NOT NULL AND status IN ('open', 'deferred')"
    )


def test_email_sync_due_index_matches_dispatcher_filters() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    index_calls = {call.args[0]: call for call in operation_proxy.create_index.call_args_list}
    migration_index = index_calls["ix_email_connections_sync_due"]
    assert migration_index.args[2] == [
        "status",
        "next_sync_at",
        "sync_lease_expires_at",
    ]

    model_index = next(
        index
        for index in Base.metadata.tables["email_connections"].indexes
        if index.name == "ix_email_connections_sync_due"
    )
    assert [column.name for column in model_index.columns] == [
        "status",
        "next_sync_at",
        "sync_lease_expires_at",
    ]


def test_email_migration_columns_match_the_orm_models() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    for call in operation_proxy.create_table.call_args_list:
        table_name = call.args[0]
        migration_columns = {item.name for item in call.args[1:] if isinstance(item, sa.Column)}
        later_columns = {"owner_user_id"}
        if table_name == "email_connections":
            later_columns.update({"ai_processing_enabled", "ai_enabled_at"})
        assert migration_columns == (set(Base.metadata.tables[table_name].c.keys()) - later_columns)


def test_email_migration_downgrades_in_dependency_order() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.downgrade()

    assert [call.args[0] for call in operation_proxy.drop_table.call_args_list] == [
        "email_activity_events",
        "email_review_items",
        "email_artifact_documents",
        "email_artifacts",
        "email_messages",
        "email_oauth_states",
        "email_connections",
    ]
