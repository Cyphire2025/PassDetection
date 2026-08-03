from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from app.infrastructure.database.gc_mobile_models import MobilePushDeliveryModel


def _load_migration():  # type: ignore[no-untyped-def]
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0076_mobile_push_receipts.py"
    )
    spec = importlib.util.spec_from_file_location("mobile_push_receipts_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_creates_new_delivery_table_without_rewriting_existing_tables() -> None:
    migration = _load_migration()
    assert migration.revision == "0076_mobile_push_receipts"
    assert migration.down_revision == "0075_mobile_group_session_metrics_index"

    operations: list[tuple[str, object]] = []

    class OperationProxy:
        def create_table(self, name, *items):  # type: ignore[no-untyped-def]
            operations.append(("create_table", (name, items)))

        def create_index(  # type: ignore[no-untyped-def]
            self, name, table_name, columns, **kwargs
        ):
            operations.append(
                ("create_index", (name, table_name, tuple(columns), kwargs))
            )

    original = migration.op
    migration.op = OperationProxy()
    try:
        migration.upgrade()
    finally:
        migration.op = original

    tables = [payload for action, payload in operations if action == "create_table"]
    assert len(tables) == 1
    assert tables[0][0] == "mobile_push_deliveries"
    columns = {item.name: item for item in tables[0][1] if hasattr(item, "type")}
    assert columns["provider_ticket_id"].nullable is True
    assert columns["next_attempt_at"].nullable is False
    assert columns["send_attempts"].server_default.arg == "0"

    indexes = {
        payload[0]: payload
        for action, payload in operations
        if action == "create_index"
    }
    assert indexes["ix_mobile_push_delivery_due"][2] == (
        "provider",
        "status",
        "next_attempt_at",
    )
    assert indexes["uq_mobile_push_delivery_provider_ticket"][3]["unique"] is True


def test_orm_enforces_idempotent_target_and_monotonic_terminal_shapes() -> None:
    table = MobilePushDeliveryModel.__table__
    constraints = {
        constraint.name: constraint
        for constraint in table.constraints
        if isinstance(constraint, (CheckConstraint, UniqueConstraint))
    }
    indexes = {index.name: index for index in table.indexes}

    target = constraints["uq_mobile_push_delivery_target"]
    assert tuple(column.name for column in target.columns) == (
        "notification_id",
        "registration_id",
    )
    assert "delivered_at IS NOT NULL" in str(
        constraints["ck_mobile_push_delivery_delivered_shape"].sqltext
    )
    assert "failed_at IS NOT NULL" in str(
        constraints["ck_mobile_push_delivery_failed_shape"].sqltext
    )
    due = indexes["ix_mobile_push_delivery_due"]
    assert isinstance(due, Index)
    assert tuple(column.name for column in due.columns) == (
        "provider",
        "status",
        "next_attempt_at",
    )
