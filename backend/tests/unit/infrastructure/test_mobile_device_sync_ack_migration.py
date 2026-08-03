from __future__ import annotations

import importlib.util
from contextlib import nullcontext
from pathlib import Path

from sqlalchemy import Index

from app.infrastructure.database.gc_mobile_models import MobileDeviceSessionModel


def _load_migration():  # type: ignore[no-untyped-def]
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0074_mobile_device_sync_ack.py"
    )
    spec = importlib.util.spec_from_file_location("mobile_device_sync_ack_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_metrics_index_migration():  # type: ignore[no-untyped-def]
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0075_mobile_group_session_metrics_index.py"
    )
    spec = importlib.util.spec_from_file_location("mobile_group_session_metrics_index", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_adds_nullable_device_sync_acknowledgement() -> None:
    migration = _load_migration()
    assert migration.revision == "0074_mobile_device_sync_ack"
    assert migration.down_revision == "0073_mobile_otp_single_pending_challenge"

    operations: list[tuple[str, object]] = []

    class OperationProxy:
        def add_column(self, table_name, column):  # type: ignore[no-untyped-def]
            operations.append(("add_column", (table_name, column)))

    original = migration.op
    migration.op = OperationProxy()
    try:
        migration.upgrade()
    finally:
        migration.op = original

    table_name, column = operations[0][1]
    assert table_name == "mobile_device_sessions"
    assert column.name == "last_sync_acknowledged_at"
    assert column.nullable is True
    assert column.server_default is None


def test_followup_migration_builds_group_metrics_index_concurrently() -> None:
    migration = _load_metrics_index_migration()
    assert migration.revision == "0075_mobile_group_session_metrics_index"
    assert migration.down_revision == "0074_mobile_device_sync_ack"

    operations: list[tuple[str, object]] = []

    class OperationProxy:
        def create_index(  # type: ignore[no-untyped-def]
            self, name, table_name, columns, **kwargs
        ):
            operations.append(("create_index", (name, table_name, tuple(columns), kwargs)))

        def get_context(self):  # type: ignore[no-untyped-def]
            return self

        def autocommit_block(self):  # type: ignore[no-untyped-def]
            return nullcontext()

    original = migration.op
    migration.op = OperationProxy()
    try:
        migration.upgrade()
    finally:
        migration.op = original

    index = next(payload for action, payload in operations if action == "create_index")
    assert index[0:3] == (
        "ix_mobile_session_group_status_expiry",
        "mobile_device_sessions",
        ("agency_id", "selected_gc_group_access_id", "status", "expires_at"),
    )
    assert index[3]["unique"] is False
    assert index[3]["postgresql_concurrently"] is True


def test_orm_exposes_device_sync_acknowledgement_column() -> None:
    column = MobileDeviceSessionModel.__table__.c.last_sync_acknowledged_at
    assert column.nullable is True
    assert column.server_default is None
    indexes = {index.name: index for index in MobileDeviceSessionModel.__table__.indexes}
    index = indexes["ix_mobile_session_group_status_expiry"]
    assert isinstance(index, Index)
    assert tuple(column.name for column in index.columns) == (
        "agency_id",
        "selected_gc_group_access_id",
        "status",
        "expires_at",
    )
