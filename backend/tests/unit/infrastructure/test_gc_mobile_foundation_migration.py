from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import app.infrastructure.database.gc_mobile_models  # noqa: F401
from app.infrastructure.database.models import Base

_TABLES = (
    "client_organizations",
    "client_manager_profiles",
    "gc_group_access",
    "client_manager_group_assignments",
    "gc_common_documents",
    "gc_itinerary_versions",
    "gc_itinerary_days",
    "gc_itinerary_items",
    "gc_announcements",
    "mobile_passenger_identities",
    "mobile_document_metadata_cache",
    "mobile_otp_challenges",
    "mobile_device_sessions",
    "mobile_refresh_tokens",
    "mobile_push_registrations",
    "mobile_notifications",
    "mobile_sync_changes",
    "passenger_family_delegations",
    "mobile_idempotency_receipts",
    "mobile_incidents",
)

# The current model reflects later migrations. Keep the immutable foundation
# contract pinned to the value that 0069 actually installed.
_FOUNDATION_SERVER_DEFAULT_OVERRIDES = {
    ("client_manager_profiles", "force_password_change"): "true",
}


def _load_migration():  # type: ignore[no-untyped-def]
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0069_gc_mobile_foundation.py"
    )
    spec = importlib.util.spec_from_file_location("gc_mobile_foundation_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _compiled_type(column: sa.Column) -> str:
    return str(column.type.compile(dialect=postgresql.dialect()))


def _server_default(column: sa.Column) -> object:
    default = column.server_default
    if default is None:
        return None
    if isinstance(default, sa.Identity):
        return ("identity", default.always)
    return str(default.arg)


def _constraint_signature(constraint: sa.Constraint) -> tuple[object, ...]:
    if isinstance(constraint, sa.CheckConstraint):
        return ("check", constraint.name, " ".join(str(constraint.sqltext).split()))
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
    raise AssertionError(f"Unexpected constraint: {type(constraint).__name__}")


def _foundation_constraint_signatures(
    table_name: str,
    model_constraints: set[tuple[object, ...]],
) -> set[tuple[object, ...]]:
    """Project the current ORM back to the 0069 foundation boundary.

    Migration 0071 intentionally strengthens passenger ownership constraints;
    this test still verifies the immutable 0069 migration while the dedicated
    0071 contract test verifies the final model.
    """

    projected = set(model_constraints)
    if table_name == "mobile_passenger_identities":
        projected.discard((
            "unique",
            "uq_mobile_passenger_identity_document_scope",
            ("id", "gc_group_access_id", "agency_id", "group_id", "passenger_submission_id"),
        ))
        projected.discard((
            "foreign_key",
            "fk_mobile_passenger_identity_submission_scope",
            ("passenger_submission_id", "agency_id", "group_id"),
            (
                "passport_submissions.id",
                "passport_submissions.agency_id",
                "passport_submissions.group_id",
            ),
            "CASCADE",
        ))
        projected.add((
            "foreign_key",
            None,
            ("passenger_submission_id",),
            ("passport_submissions.id",),
            "CASCADE",
        ))
    if table_name == "mobile_document_metadata_cache":
        projected.discard((
            "foreign_key",
            "fk_mobile_document_cache_identity",
            (
                "passenger_identity_id",
                "gc_group_access_id",
                "agency_id",
                "group_id",
                "passenger_submission_id",
            ),
            (
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
                "mobile_passenger_identities.passenger_submission_id",
            ),
            "CASCADE",
        ))
        projected.add((
            "foreign_key",
            "fk_mobile_document_cache_identity",
            ("passenger_identity_id", "gc_group_access_id", "agency_id", "group_id"),
            (
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
            ),
            "CASCADE",
        ))
        projected.add((
            "foreign_key",
            None,
            ("passenger_submission_id",),
            ("passport_submissions.id",),
            "CASCADE",
        ))
    return projected


def test_gc_mobile_models_register_the_complete_schema() -> None:
    assert all(table_name in Base.metadata.tables for table_name in _TABLES)

    access = Base.metadata.tables["gc_group_access"]
    assert str(access.c.is_enabled.server_default.arg) == "false"
    assert str(access.c.passenger_access_enabled.server_default.arg) == "false"
    assert str(access.c.client_manager_access_enabled.server_default.arg) == "false"
    assert str(access.c.coordinator_access_enabled.server_default.arg) == "false"

    assignment = Base.metadata.tables["client_manager_group_assignments"]
    assert str(assignment.c.personal_document_access_enabled.server_default.arg) == "false"
    delegation = Base.metadata.tables["passenger_family_delegations"]
    assert str(delegation.c.is_enabled.server_default.arg) == "false"
    assert str(delegation.c.can_view_documents.server_default.arg) == "false"
    assert str(delegation.c.can_view_qr.server_default.arg) == "false"


def test_mobile_secret_tables_store_hashes_or_ciphertext_only() -> None:
    otp_columns = set(Base.metadata.tables["mobile_otp_challenges"].c.keys())
    assert {"code_hash", "phone_lookup_hash", "challenge_token_hash"} <= otp_columns
    assert {"otp", "code", "phone_number"}.isdisjoint(otp_columns)

    refresh_columns = set(Base.metadata.tables["mobile_refresh_tokens"].c.keys())
    assert "token_hash" in refresh_columns
    assert "token" not in refresh_columns

    push_columns = set(Base.metadata.tables["mobile_push_registrations"].c.keys())
    assert {"token_ciphertext", "token_lookup_hash", "token_key_version"} <= push_columns
    assert "token" not in push_columns


def test_gc_mobile_migration_matches_orm_tables_and_indexes() -> None:
    migration = _load_migration()
    assert migration.revision == "0069_gc_mobile_foundation"
    assert migration.down_revision == "0068_document_chunk_limits"

    operation_proxy = MagicMock()
    migration.op = operation_proxy
    migration.upgrade()

    assert operation_proxy.get_context.return_value.autocommit_block.called
    enum_statements = [str(call.args[0]) for call in operation_proxy.execute.call_args_list]
    assert any("ADD VALUE IF NOT EXISTS 'client_manager'" in item for item in enum_statements)

    table_calls = {call.args[0]: call for call in operation_proxy.create_table.call_args_list}
    assert tuple(table_calls) == _TABLES
    for table_name, table_call in table_calls.items():
        model_table = Base.metadata.tables[table_name]
        migration_columns = {
            item.name: item for item in table_call.args[1:] if isinstance(item, sa.Column)
        }
        model_column_names = set(model_table.c.keys())
        if table_name == "mobile_device_sessions":
            # Added by later migrations; the immutable foundation migration must
            # not be rewritten after production databases have applied it.
            model_column_names.discard("account_id")
            model_column_names.discard("last_sync_acknowledged_at")
        assert set(migration_columns) == model_column_names
        for column_name, migration_column in migration_columns.items():
            model_column = model_table.c[column_name]
            assert _compiled_type(migration_column) == _compiled_type(model_column)
            assert migration_column.nullable is model_column.nullable
            expected_default = _FOUNDATION_SERVER_DEFAULT_OVERRIDES.get(
                (table_name, column_name),
                _server_default(model_column),
            )
            assert _server_default(migration_column) == expected_default

        migration_constraints = {
            _constraint_signature(item)
            for item in table_call.args[1:]
            if isinstance(item, sa.Constraint)
        }
        model_constraints = _foundation_constraint_signatures(
            table_name,
            {_constraint_signature(item) for item in model_table.constraints},
        )
        assert migration_constraints == model_constraints

    migration_indexes = {
        call.args[0]: (
            call.args[1],
            tuple(call.args[2]),
            call.kwargs.get("unique", False),
            str(call.kwargs.get("postgresql_where")),
            str(call.kwargs.get("sqlite_where")),
        )
        for call in operation_proxy.create_index.call_args_list
    }
    model_indexes: dict[str, tuple[object, ...]] = {}
    for table_name in _TABLES:
        for index in Base.metadata.tables[table_name].indexes:
            if index.name in {
                "ix_client_manager_admin_list",
                "ix_mobile_session_account",
                "ix_mobile_session_group_status_expiry",
                "uq_mobile_otp_pending_phone",
            }:
                continue
            postgres_where = index.dialect_options["postgresql"].get("where")
            sqlite_where = index.dialect_options["sqlite"].get("where")
            assert index.name is not None
            model_indexes[index.name] = (
                table_name,
                tuple(column.name for column in index.columns),
                bool(index.unique),
                str(postgres_where),
                str(sqlite_where),
            )
    assert migration_indexes == model_indexes


def test_gc_mobile_migration_downgrade_uses_reverse_dependency_order() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    migration.op = operation_proxy

    migration.downgrade()

    assert [call.args[0] for call in operation_proxy.drop_table.call_args_list] == list(
        reversed(_TABLES)
    )
    operation_proxy.execute.assert_not_called()
