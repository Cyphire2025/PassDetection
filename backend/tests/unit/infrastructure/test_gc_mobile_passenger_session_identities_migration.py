from __future__ import annotations

import importlib.util
from contextlib import nullcontext
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, PrimaryKeyConstraint

from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel,
    MobilePassengerSessionIdentityModel,
)


def _load_migration():  # type: ignore[no-untyped-def]
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0072_gc_mobile_passenger_session_identities.py"
    )
    spec = importlib.util.spec_from_file_location(
        "gc_mobile_passenger_session_identities_migration", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_session_identity_migration_follows_current_head_and_backfills_fail_closed() -> None:
    migration = _load_migration()
    assert migration.revision == "0072_mobile_session_identities"
    assert migration.down_revision == "0071_mobile_scope_constraints"

    operations: list[tuple[str, object]] = []

    class OperationProxy:
        def add_column(self, table_name, column):  # type: ignore[no-untyped-def]
            operations.append(("add_column", (table_name, column)))

        def alter_column(self, table_name, column_name, **kwargs):  # type: ignore[no-untyped-def]
            operations.append(("alter_column", (table_name, column_name, kwargs)))

        def create_table(self, name, *items):  # type: ignore[no-untyped-def]
            operations.append(("create_table", (name, items)))

        def create_index(self, name, table_name, columns, unique=False, **kwargs):  # type: ignore[no-untyped-def]
            operations.append(
                ("create_index", (name, table_name, tuple(columns), unique, kwargs))
            )

        def create_check_constraint(self, name, table_name, condition, **kwargs):  # type: ignore[no-untyped-def]
            operations.append(
                ("create_check_constraint", (name, table_name, condition, kwargs))
            )

        def drop_constraint(self, name, table_name, **kwargs):  # type: ignore[no-untyped-def]
            operations.append(("drop_constraint", (name, table_name, kwargs)))

        def get_context(self):  # type: ignore[no-untyped-def]
            return self

        def autocommit_block(self):  # type: ignore[no-untyped-def]
            return nullcontext()

        def execute(self, sql):  # type: ignore[no-untyped-def]
            operations.append(("execute", sql))

    original = migration.op
    migration.op = OperationProxy()
    try:
        migration.upgrade()
    finally:
        migration.op = original

    table_name, constraints = next(
        payload for action, payload in operations if action == "create_table"
    )
    assert table_name == "mobile_passenger_session_identities"
    foreign_keys = {
        item.name: (tuple(item.column_keys), tuple(element.target_fullname for element in item.elements))
        for item in constraints
        if isinstance(item, ForeignKeyConstraint)
    }
    assert foreign_keys["fk_mobile_passenger_session_identity_session"] == (
        ("session_id", "agency_id"),
        ("mobile_device_sessions.id", "mobile_device_sessions.agency_id"),
    )
    assert foreign_keys["fk_mobile_passenger_session_identity_scope"] == (
        ("passenger_identity_id", "gc_group_access_id", "agency_id", "group_id"),
        (
            "mobile_passenger_identities.id",
            "mobile_passenger_identities.gc_group_access_id",
            "mobile_passenger_identities.agency_id",
            "mobile_passenger_identities.group_id",
        ),
    )
    account_table, account_column = next(
        payload for action, payload in operations if action == "add_column"
    )
    assert account_table == "mobile_device_sessions"
    assert account_column.name == "account_id"
    assert account_column.nullable is True
    not_null_check = next(
        payload for action, payload in operations if action == "create_check_constraint"
    )
    assert not_null_check[0:3] == (
        "ck_mobile_device_sessions_account_id_not_null",
        "mobile_device_sessions",
        "account_id IS NOT NULL",
    )
    assert not_null_check[3]["postgresql_not_valid"] is True
    account_backfill_sql = next(
        payload
        for action, payload in operations
        if action == "execute" and "SET account_id" in payload
    )
    assert "COALESCE(passenger_identity_id, user_id)" in account_backfill_sql
    backfill_sql = next(
        payload
        for action, payload in operations
        if action == "execute" and "INSERT INTO mobile_passenger_session_identities" in payload
    )
    assert "identity.agency_id = session.agency_id" in backfill_sql
    assert "identity.gc_group_access_id = session.selected_gc_group_access_id" in backfill_sql
    assert "identity.group_id = session.selected_group_id" in backfill_sql
    session_index = next(
        payload
        for action, payload in operations
        if action == "create_index" and payload[0] == "ix_mobile_session_account"
    )
    assert session_index[4]["postgresql_concurrently"] is True


def test_session_identity_model_enforces_scope_generation_and_exact_membership() -> None:
    account_column = MobileDeviceSessionModel.__table__.c.account_id
    assert account_column.nullable is False

    table = MobilePassengerSessionIdentityModel.__table__
    primary_key = next(
        item for item in table.constraints if isinstance(item, PrimaryKeyConstraint)
    )
    foreign_keys = {
        item.name: tuple(column.name for column in item.columns)
        for item in table.constraints
        if isinstance(item, ForeignKeyConstraint)
    }
    checks = {
        item.name: str(item.sqltext)
        for item in table.constraints
        if isinstance(item, CheckConstraint)
    }

    assert tuple(column.name for column in primary_key.columns) == (
        "session_id",
        "passenger_identity_id",
    )
    assert foreign_keys["fk_mobile_passenger_session_identity_session"] == (
        "session_id",
        "agency_id",
    )
    assert foreign_keys["fk_mobile_passenger_session_identity_scope"] == (
        "passenger_identity_id",
        "gc_group_access_id",
        "agency_id",
        "group_id",
    )
    assert checks["ck_mobile_passenger_session_identity_generation"] == (
        "identity_claim_generation >= 0"
    )
