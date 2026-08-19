from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint, Index

from app.infrastructure.database.gc_mobile_models import MobileAppAttestKeyModel


def _load_migration():  # type: ignore[no-untyped-def]
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0081_mobile_app_attest_keys.py"
    )
    spec = importlib.util.spec_from_file_location("mobile_app_attest_keys_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_is_additive_and_builds_hash_only_key_state() -> None:
    migration = _load_migration()
    assert migration.revision == "0081_mobile_app_attest_keys"
    assert migration.down_revision == "0080_domestic_ticket_lanes"

    operations: list[tuple[str, object]] = []

    class OperationProxy:
        def create_table(self, name, *items):  # type: ignore[no-untyped-def]
            operations.append(("create_table", (name, items)))

        def create_index(  # type: ignore[no-untyped-def]
            self,
            name,
            table_name,
            columns,
            **kwargs,
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
    assert tables[0][0] == "mobile_app_attest_keys"
    columns = {item.name: item for item in tables[0][1] if hasattr(item, "type")}
    assert "key_id" not in columns
    assert "attestation_object" not in columns
    assert "private_key" not in columns
    assert columns["device_identifier_hash"].type.length == 64
    assert columns["key_identifier_hash"].type.length == 64
    assert columns["verification_material"].nullable is False
    assert columns["assertion_counter"].server_default.arg == "0"

    indexes = {
        payload[0]: payload
        for action, payload in operations
        if action == "create_index"
    }
    assert indexes["uq_mobile_app_attest_account_device_active"][3]["unique"] is True
    assert indexes["uq_mobile_app_attest_key_active"][3]["unique"] is True
    assert "status = 'active'" in str(
        indexes["uq_mobile_app_attest_key_active"][3]["postgresql_where"]
    )


def test_orm_matches_counter_state_and_active_uniqueness_contract() -> None:
    table = MobileAppAttestKeyModel.__table__
    constraints = {
        constraint.name: constraint
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    indexes = {index.name: index for index in table.indexes}

    assert "assertion_counter >= 0" in str(
        constraints["ck_mobile_app_attest_counter"].sqltext
    )
    assert "revoked_at IS NULL" in str(
        constraints["ck_mobile_app_attest_state_shape"].sqltext
    )
    account_device = indexes["uq_mobile_app_attest_account_device_active"]
    assert isinstance(account_device, Index)
    assert account_device.unique is True
    assert tuple(column.name for column in account_device.columns) == (
        "agency_id",
        "account_id",
        "device_identifier_hash",
    )
    key = indexes["uq_mobile_app_attest_key_active"]
    assert key.unique is True
    assert tuple(column.name for column in key.columns) == ("key_identifier_hash",)
