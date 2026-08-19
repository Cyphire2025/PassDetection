from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint

from app.domain.value_objects.trip_timezone import DEFAULT_TRIP_TIMEZONE
from app.infrastructure.database.models import ClientGroupModel


def _load_migration():  # type: ignore[no-untyped-def]
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0082_canonical_trip_timezone.py"
    )
    spec = importlib.util.spec_from_file_location("canonical_trip_timezone_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_timezone_migration_is_additive_backfilled_and_chained_to_0081() -> None:
    migration = _load_migration()
    assert migration.revision == "0082_canonical_trip_timezone"
    assert migration.down_revision == "0081_mobile_app_attest_keys"

    operations: list[tuple[str, object]] = []

    class OperationProxy:
        def add_column(self, table_name, column):  # type: ignore[no-untyped-def]
            operations.append(("add_column", (table_name, column)))

        def create_check_constraint(  # type: ignore[no-untyped-def]
            self,
            name,
            table_name,
            condition,
        ):
            operations.append(("create_check_constraint", (name, table_name, condition)))

    original = migration.op
    migration.op = OperationProxy()
    try:
        migration.upgrade()
    finally:
        migration.op = original

    table_name, column = next(payload for action, payload in operations if action == "add_column")
    assert table_name == "client_groups"
    assert column.name == "timezone"
    assert column.nullable is False
    assert column.type.length == 64
    assert str(column.server_default.arg) == f"'{DEFAULT_TRIP_TIMEZONE}'"
    constraint = next(
        payload for action, payload in operations if action == "create_check_constraint"
    )
    assert constraint[0] == "ck_client_groups_timezone_shape"
    assert "trim(timezone)" in constraint[2]


def test_timezone_orm_matches_migration_default_and_shape_constraint() -> None:
    column = ClientGroupModel.__table__.c.timezone
    constraints = {
        constraint.name: constraint
        for constraint in ClientGroupModel.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert column.nullable is False
    assert column.type.length == 64
    assert column.default.arg == DEFAULT_TRIP_TIMEZONE
    assert column.server_default.arg == DEFAULT_TRIP_TIMEZONE
    assert "trim(timezone)" in str(constraints["ck_client_groups_timezone_shape"].sqltext)
