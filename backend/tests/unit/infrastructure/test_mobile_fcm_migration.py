"""0095 changes only constraints and refuses to discard FCM delivery history."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.infrastructure.database.gc_mobile_models import MobilePushDeliveryModel


def _migration():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0095_mobile_fcm_delivery.py"
    spec = importlib.util.spec_from_file_location("mobile_fcm_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConstraintOperations:
    """Deliberately exposes no table/column/index removal or data-write operation."""

    def __init__(self, connection=None):
        self.connection = connection
        self.calls = []

    def drop_constraint(self, name, table, *, type_):
        assert type_ == "check" and table == "mobile_push_deliveries"
        self.calls.append(("drop", name))

    def create_check_constraint(self, name, table, condition):
        assert table == "mobile_push_deliveries"
        self.calls.append(("create", name, condition))

    def get_bind(self):
        assert self.connection is not None
        return self.connection


def test_upgrade_changes_only_two_checks_and_matches_model_constraints():
    migration = _migration()
    operations = ConstraintOperations()
    migration.op = operations
    migration.upgrade()
    assert migration.revision == "0095_mobile_fcm_delivery"
    assert migration.down_revision == "0094_whatsapp_receipt_inbox"
    assert [call[:2] for call in operations.calls] == [
        ("drop", "ck_mobile_push_delivery_status"),
        ("create", "ck_mobile_push_delivery_status"),
        ("drop", "ck_mobile_push_delivery_receipt_shape"),
        ("create", "ck_mobile_push_delivery_receipt_shape"),
    ]
    constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in MobilePushDeliveryModel.__table__.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    for operation, name, *condition in operations.calls:
        if operation == "create":
            assert condition[0] == constraints[name]


@pytest.mark.parametrize("state", ["provider_accepted", "unknown"])
def test_downgrade_refuses_new_states_before_constraint_change_and_preserves_rows(state):
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE mobile_push_deliveries (status TEXT)"))
            connection.execute(
                sa.text("INSERT INTO mobile_push_deliveries (status) VALUES (:state)"),
                {"state": state},
            )
            operations = ConstraintOperations(connection)
            migration.op = operations
            with pytest.raises(RuntimeError, match="FCM delivery history requires schema 0095"):
                migration.downgrade()
            assert operations.calls == []
            assert connection.execute(
                sa.text("SELECT status FROM mobile_push_deliveries")
            ).scalars().all() == [state]
    finally:
        engine.dispose()


def test_downgrade_without_new_states_restores_old_checks_without_rewriting_rows():
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    states = ["submitting", "retry", "receipt_pending", "delivered", "failed", "cancelled"]
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE mobile_push_deliveries (status TEXT)"))
            connection.execute(
                sa.text("INSERT INTO mobile_push_deliveries (status) VALUES (:state)"),
                [{"state": state} for state in states],
            )
            operations = ConstraintOperations(connection)
            migration.op = operations
            migration.downgrade()
            assert len(operations.calls) == 4
            conditions = [call[2] for call in operations.calls if call[0] == "create"]
            assert all(
                "provider_accepted" not in value and "unknown" not in value for value in conditions
            )
            assert (
                conditions[1]
                == "status NOT IN ('receipt_pending', 'delivered') OR provider_ticket_id IS NOT NULL"
            )
            assert (
                connection.execute(sa.text("SELECT status FROM mobile_push_deliveries"))
                .scalars()
                .all()
                == states
            )
    finally:
        engine.dispose()
