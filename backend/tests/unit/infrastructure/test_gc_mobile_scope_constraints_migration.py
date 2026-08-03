from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from app.infrastructure.database.gc_mobile_models import (
    MobileDocumentMetadataCacheModel,
    MobilePassengerIdentityModel,
)
from app.infrastructure.database.models import PassportSubmissionModel


def _load_migration():
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0071_gc_mobile_passenger_scope_constraints.py"
    )
    spec = importlib.util.spec_from_file_location("gc_mobile_scope_migration", migration_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"alembic": SimpleNamespace(op=MagicMock())}):
        spec.loader.exec_module(module)
    return module


def _constraint_columns(model, constraint_type):
    return {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if isinstance(constraint, constraint_type) and constraint.name
    }


def test_scope_migration_follows_head_and_validates_existing_rows() -> None:
    migration = _load_migration()
    assert migration.revision == "0071_mobile_scope_constraints"
    assert migration.down_revision == "0070_mobile_ops_indexes"

    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    executed_sql = [str(call.args[0]) for call in operation_proxy.execute.call_args_list]
    validation_sql = next(
        statement
        for statement in executed_sql
        if "mobile passenger identity scope mismatch" in statement
    )
    assert "mobile passenger identity scope mismatch" in validation_sql
    assert "mobile document passenger scope mismatch" in validation_sql
    assert any("UNIQUE USING INDEX uq_passport_submissions_mobile_scope" in item for item in executed_sql)
    assert any(
        "UNIQUE USING INDEX uq_mobile_passenger_identity_document_scope" in item
        for item in executed_sql
    )
    assert operation_proxy.get_context.return_value.autocommit_block.call_count == 2
    assert all(
        call.kwargs.get("postgresql_concurrently") is True
        for call in operation_proxy.create_index.call_args_list
    )
    created_foreign_keys = {
        call.args[0]: (tuple(call.args[3]), tuple(call.args[4]))
        for call in operation_proxy.create_foreign_key.call_args_list
    }
    assert created_foreign_keys["fk_mobile_passenger_identity_submission_scope"] == (
        ("passenger_submission_id", "agency_id", "group_id"),
        ("id", "agency_id", "group_id"),
    )
    assert created_foreign_keys["fk_mobile_document_cache_identity"] == (
        (
            "passenger_identity_id",
            "gc_group_access_id",
            "agency_id",
            "group_id",
            "passenger_submission_id",
        ),
        ("id", "gc_group_access_id", "agency_id", "group_id", "passenger_submission_id"),
    )
    assert all(
        call.kwargs.get("postgresql_not_valid") is True
        for call in operation_proxy.create_foreign_key.call_args_list
    )
    assert any(
        "VALIDATE CONSTRAINT fk_mobile_passenger_identity_submission_scope" in item
        for item in executed_sql
    )
    assert any(
        "VALIDATE CONSTRAINT fk_mobile_document_cache_identity" in item
        for item in executed_sql
    )


def test_models_enforce_the_same_tenant_group_and_passenger_scope() -> None:
    passport_uniques = _constraint_columns(PassportSubmissionModel, UniqueConstraint)
    identity_uniques = _constraint_columns(MobilePassengerIdentityModel, UniqueConstraint)
    identity_foreign_keys = _constraint_columns(
        MobilePassengerIdentityModel,
        ForeignKeyConstraint,
    )
    document_foreign_keys = _constraint_columns(
        MobileDocumentMetadataCacheModel,
        ForeignKeyConstraint,
    )

    assert passport_uniques["uq_passport_submissions_mobile_scope"] == (
        "id",
        "agency_id",
        "group_id",
    )
    assert identity_uniques["uq_mobile_passenger_identity_document_scope"] == (
        "id",
        "gc_group_access_id",
        "agency_id",
        "group_id",
        "passenger_submission_id",
    )
    assert identity_foreign_keys["fk_mobile_passenger_identity_submission_scope"] == (
        "passenger_submission_id",
        "agency_id",
        "group_id",
    )
    assert document_foreign_keys["fk_mobile_document_cache_identity"] == (
        "passenger_identity_id",
        "gc_group_access_id",
        "agency_id",
        "group_id",
        "passenger_submission_id",
    )
