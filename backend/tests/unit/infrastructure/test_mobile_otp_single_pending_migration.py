from __future__ import annotations

import importlib.util
from contextlib import nullcontext
from pathlib import Path

from sqlalchemy import Index

from app.infrastructure.database.gc_mobile_models import MobileOTPChallengeModel


def _load_migration():  # type: ignore[no-untyped-def]
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0073_mobile_otp_single_pending_challenge.py"
    )
    spec = importlib.util.spec_from_file_location(
        "mobile_otp_single_pending_migration", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_deduplicates_before_creating_pending_challenge_guard() -> None:
    migration = _load_migration()
    assert migration.revision == "0073_mobile_otp_single_pending_challenge"
    assert migration.down_revision == "0072_gc_mobile_passenger_session_identities"

    operations: list[tuple[str, object]] = []

    class OperationProxy:
        def execute(self, sql):  # type: ignore[no-untyped-def]
            operations.append(("execute", sql))

        def create_index(  # type: ignore[no-untyped-def]
            self, name, table_name, columns, **kwargs
        ):
            operations.append(
                ("create_index", (name, table_name, tuple(columns), kwargs))
            )

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

    cleanup_sql = next(payload for action, payload in operations if action == "execute")
    assert "PARTITION BY phone_lookup_hash" in cleanup_sql
    assert "pending_rank > 1" in cleanup_sql
    index = next(payload for action, payload in operations if action == "create_index")
    assert index[0:3] == (
        "uq_mobile_otp_pending_phone",
        "mobile_otp_challenges",
        ("phone_lookup_hash",),
    )
    assert index[3]["unique"] is True
    assert str(index[3]["postgresql_where"]) == "status = 'pending'"
    assert index[3]["postgresql_concurrently"] is True


def test_orm_has_matching_partial_unique_pending_challenge_index() -> None:
    indexes = {
        index.name: index for index in MobileOTPChallengeModel.__table__.indexes
    }
    index = indexes["uq_mobile_otp_pending_phone"]
    assert isinstance(index, Index)
    assert index.unique is True
    assert tuple(column.name for column in index.columns) == ("phone_lookup_hash",)
    assert str(index.dialect_options["postgresql"]["where"]) == "status = 'pending'"
