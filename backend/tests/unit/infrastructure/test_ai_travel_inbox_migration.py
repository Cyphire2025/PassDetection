from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import app.infrastructure.database.email_ai_models  # noqa: F401
from app.infrastructure.database.models import Base

_AI_TABLES = (
    "email_ai_rollout_policies",
    "email_ai_analyses",
    "email_detected_deadlines",
    "email_action_proposals",
    "email_reply_drafts",
    "email_ai_feedback",
)
_NOTIFICATION_COLUMNS = {
    "priority",
    "category",
    "dedupe_key",
    "metadata",
}


def _load_migration():
    migration_path = (
        Path(__file__).resolve().parents[3] / "alembic" / "versions" / "0065_ai_travel_inbox.py"
    )
    spec = importlib.util.spec_from_file_location(
        "ai_travel_inbox_migration",
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


def _columns_from_table_call(table_call) -> dict[str, sa.Column]:  # type: ignore[no-untyped-def]
    return {item.name: item for item in table_call.args[1:] if isinstance(item, sa.Column)}


def _compiled_type(column: sa.Column) -> str:
    return str(column.type.compile(dialect=postgresql.dialect()))


def _server_default(column: sa.Column) -> str | None:
    if column.server_default is None:
        return None
    return str(column.server_default.arg)


def _constraint_signature(constraint: sa.Constraint) -> tuple[object, ...]:
    if isinstance(constraint, sa.CheckConstraint):
        return (
            "check",
            constraint.name,
            " ".join(str(constraint.sqltext).split()),
        )
    if isinstance(constraint, sa.ForeignKeyConstraint):
        return (
            "foreign_key",
            constraint.name,
            tuple(constraint.column_keys),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.ondelete,
        )
    if isinstance(constraint, sa.UniqueConstraint):
        columns = (
            tuple(column.name for column in constraint.columns)
            if constraint.columns
            else tuple(constraint._pending_colargs)
        )
        return ("unique", constraint.name, columns)
    if isinstance(constraint, sa.PrimaryKeyConstraint):
        columns = (
            tuple(column.name for column in constraint.columns)
            if constraint.columns
            else tuple(constraint._pending_colargs)
        )
        return ("primary_key", constraint.name, columns)
    raise AssertionError(f"Unexpected constraint type: {type(constraint).__name__}")


def _migration_constraint_signatures(table_call) -> set[tuple[object, ...]]:  # type: ignore[no-untyped-def]
    return {
        _constraint_signature(item)
        for item in table_call.args[1:]
        if isinstance(item, sa.Constraint)
    }


def _model_constraint_signatures(table_name: str) -> set[tuple[object, ...]]:
    return {
        _constraint_signature(constraint)
        for constraint in Base.metadata.tables[table_name].constraints
    }


def test_owner_migration_follows_current_head_and_adds_rollout_switch() -> None:
    migration = _load_migration()
    assert migration.revision == "0065_ai_travel_inbox"
    assert migration.down_revision == "0064_document_resends"

    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    owner_tables = {
        call.args[0]
        for call in operation_proxy.add_column.call_args_list
        if call.args[1].name == "owner_user_id"
    }
    assert owner_tables == set(migration._OWNER_TABLES)
    ai_column_call = next(
        call
        for call in operation_proxy.add_column.call_args_list
        if call.args[1].name == "ai_processing_enabled"
    )
    ai_column = ai_column_call.args[1]
    assert ai_column_call.args[0] == "email_connections"
    assert ai_column.nullable is False
    assert isinstance(ai_column.type, sa.Boolean)
    assert str(ai_column.server_default.arg) == "false"
    watermark_column_call = next(
        call
        for call in operation_proxy.add_column.call_args_list
        if call.args[1].name == "ai_enabled_at"
    )
    watermark_column = watermark_column_call.args[1]
    assert watermark_column_call.args[0] == "email_connections"
    assert watermark_column.nullable is True
    assert isinstance(watermark_column.type, sa.DateTime)


def test_owner_migration_backfills_only_same_agency_and_scrubs_orphans() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    statements = "\n".join(str(call.args[0]) for call in operation_proxy.execute.call_args_list)
    assert "owners.agency_id = connections.agency_id" in statements
    assert "access_token_ciphertext = NULL" in statements
    assert "refresh_token_ciphertext = NULL" in statements
    assert "status = 'disconnected'" in statements
    assert "sync_state = 'blocked'" in statements
    assert "EMAIL_OWNER_BACKFILL_REQUIRED" in statements
    assert "ALTER COLUMN owner_user_id SET NOT NULL" in statements

    readiness_call = next(
        call
        for call in operation_proxy.create_check_constraint.call_args_list
        if call.args[0] == "ck_email_connections_owner_ready"
    )
    assert "owner_user_id IS NOT NULL" in readiness_call.args[2]


def test_owner_migration_adds_composite_ownership_foreign_keys() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    foreign_keys = {
        call.args[0]: (tuple(call.args[3]), tuple(call.args[4]))
        for call in operation_proxy.create_foreign_key.call_args_list
    }
    assert foreign_keys["fk_email_messages_connection_agency_owner"] == (
        ("connection_id", "agency_id", "owner_user_id"),
        ("id", "agency_id", "owner_user_id"),
    )
    assert foreign_keys["fk_email_review_items_artifact_message_agency_owner"] == (
        ("artifact_id", "message_id", "agency_id", "owner_user_id"),
        ("id", "message_id", "agency_id", "owner_user_id"),
    )
    assert foreign_keys["fk_email_oauth_states_connection_agency_owner"] == (
        ("connection_id", "agency_id", "user_id"),
        ("id", "agency_id", "owner_user_id"),
    )


def test_owner_migration_reconciles_legacy_cross_owner_references_before_fks() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    calls = [str(call) for call in operation_proxy.mock_calls]
    oauth_cleanup = next(
        index
        for index, call in enumerate(calls)
        if "DELETE FROM email_oauth_states AS states" in call
    )
    oauth_fk = next(
        index
        for index, call in enumerate(calls)
        if "fk_email_oauth_states_connection_agency_owner" in call
    )
    duplicate_cleanup = next(
        index
        for index, call in enumerate(calls)
        if "SET duplicate_of_id = NULL" in call
    )
    duplicate_fk = next(
        index
        for index, call in enumerate(calls)
        if "fk_email_artifacts_duplicate_agency_owner" in call
    )

    assert "connections.owner_user_id = states.user_id" in calls[oauth_cleanup]
    assert "original.owner_user_id = artifacts.owner_user_id" in calls[
        duplicate_cleanup
    ]
    assert oauth_cleanup < oauth_fk
    assert duplicate_cleanup < duplicate_fk


def test_notification_migration_matches_the_current_orm_delta() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    migration_columns = {
        call.args[1].name: call.args[1]
        for call in operation_proxy.add_column.call_args_list
        if call.args[0] == "notifications"
    }
    assert set(migration_columns) == _NOTIFICATION_COLUMNS
    model_table = Base.metadata.tables["notifications"]
    for column_name, migration_column in migration_columns.items():
        model_column = model_table.c[column_name]
        assert _compiled_type(migration_column) == _compiled_type(model_column)
        assert migration_column.nullable is model_column.nullable
        assert _server_default(migration_column) == _server_default(model_column)

    notification_indexes = {
        call.args[0]: (tuple(call.args[2]), call.kwargs.get("unique", False))
        for call in operation_proxy.create_index.call_args_list
        if call.args[1] == "notifications"
    }
    assert notification_indexes == {
        "ix_notifications_priority": (("priority",), False),
        "ix_notifications_category": (("category",), False),
        "ix_notifications_user_unread_created": (
            ("user_id", "is_read", "created_at"),
            False,
        ),
    }
    unique_call = next(
        call
        for call in operation_proxy.create_unique_constraint.call_args_list
        if call.args[0] == "uq_notifications_user_dedupe_key"
    )
    assert unique_call.args[1:] == (
        "notifications",
        ["user_id", "dedupe_key"],
    )


def test_ai_migration_tables_match_current_orm_columns_and_constraints() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    assert [call.args[0] for call in operation_proxy.create_table.call_args_list] == list(
        _AI_TABLES
    )
    for table_name in _AI_TABLES:
        table_call = _table_call(operation_proxy, table_name)
        migration_columns = _columns_from_table_call(table_call)
        model_columns = Base.metadata.tables[table_name].c
        assert set(migration_columns) == set(model_columns.keys())
        for column_name, migration_column in migration_columns.items():
            model_column = model_columns[column_name]
            assert _compiled_type(migration_column) == _compiled_type(model_column)
            assert migration_column.nullable is model_column.nullable
            assert _server_default(migration_column) == _server_default(model_column)
        assert _migration_constraint_signatures(table_call) == _model_constraint_signatures(
            table_name
        )


def test_ai_migration_indexes_match_current_orm_indexes() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    migration_indexes = {
        call.args[0]: {
            "table": call.args[1],
            "columns": tuple(call.args[2]),
            "unique": call.kwargs.get("unique", False),
            "postgresql_where": (
                str(call.kwargs["postgresql_where"]) if "postgresql_where" in call.kwargs else None
            ),
            "sqlite_where": (
                str(call.kwargs["sqlite_where"]) if "sqlite_where" in call.kwargs else None
            ),
        }
        for call in operation_proxy.create_index.call_args_list
        if call.args[1] in _AI_TABLES
    }
    model_indexes = {}
    for table_name in _AI_TABLES:
        for index in Base.metadata.tables[table_name].indexes:
            postgresql_where = index.dialect_options["postgresql"].get("where")
            sqlite_where = index.dialect_options["sqlite"].get("where")
            model_indexes[index.name] = {
                "table": table_name,
                "columns": tuple(column.name for column in index.columns),
                "unique": index.unique,
                "postgresql_where": (
                    str(postgresql_where) if postgresql_where is not None else None
                ),
                "sqlite_where": str(sqlite_where) if sqlite_where is not None else None,
            }
    assert migration_indexes == model_indexes


def test_ai_migration_downgrade_drops_tables_in_dependency_order() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.downgrade()

    assert [call.args[0] for call in operation_proxy.drop_table.call_args_list] == [
        "email_ai_feedback",
        "email_reply_drafts",
        "email_action_proposals",
        "email_detected_deadlines",
        "email_ai_analyses",
        "email_ai_rollout_policies",
    ]
    notification_drop_columns = {
        call.args[1]
        for call in operation_proxy.drop_column.call_args_list
        if call.args[0] == "notifications"
    }
    assert notification_drop_columns == _NOTIFICATION_COLUMNS
