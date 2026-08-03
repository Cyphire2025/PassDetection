from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.infrastructure.database.models import (
    DistributedDocumentModel,
    PassportSubmissionModel,
)


def _load_migration():
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0070_gc_mobile_operational_indexes.py"
    )
    spec = importlib.util.spec_from_file_location(
        "gc_mobile_operational_indexes_migration",
        migration_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"alembic": SimpleNamespace(op=MagicMock())}):
        spec.loader.exec_module(module)
    return module


def test_mobile_operational_indexes_follow_head_and_are_reversible() -> None:
    migration = _load_migration()
    assert migration.revision == "0070_mobile_ops_indexes"
    assert migration.down_revision == "0069_gc_mobile_foundation"

    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()
    created = {
        call.args[0]: (
            call.args[1],
            tuple(call.args[2]),
            call.kwargs.get("postgresql_concurrently"),
            call.kwargs.get("if_not_exists"),
        )
        for call in operation_proxy.create_index.call_args_list
    }
    assert created == {
        "ix_passport_submissions_mobile_roster": (
            "passport_submissions",
            ("agency_id", "group_id", "status", "id"),
            True,
            True,
        ),
        "ix_distributed_documents_mobile_passenger": (
            "distributed_documents",
            ("agency_id", "group_id", "passenger_id", "match_status", "document_type"),
            True,
            True,
        ),
    }
    assert operation_proxy.get_context.return_value.autocommit_block.called

    operation_proxy.reset_mock()
    with patch.object(migration, "op", operation_proxy):
        migration.downgrade()
    assert [call.args[0] for call in operation_proxy.drop_index.call_args_list] == [
        "ix_distributed_documents_mobile_passenger",
        "ix_passport_submissions_mobile_roster",
    ]
    assert all(
        call.kwargs.get("postgresql_concurrently") is True
        for call in operation_proxy.drop_index.call_args_list
    )


def test_mobile_operational_index_models_match_migration_contract() -> None:
    passport_indexes = {index.name: tuple(column.name for column in index.columns) for index in PassportSubmissionModel.__table__.indexes}
    document_indexes = {index.name: tuple(column.name for column in index.columns) for index in DistributedDocumentModel.__table__.indexes}

    assert passport_indexes["ix_passport_submissions_mobile_roster"] == (
        "agency_id",
        "group_id",
        "status",
        "id",
    )
    assert document_indexes["ix_distributed_documents_mobile_passenger"] == (
        "agency_id",
        "group_id",
        "passenger_id",
        "match_status",
        "document_type",
    )
