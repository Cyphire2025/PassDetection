from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.infrastructure.database.models import StorageCleanupJobModel


def _load_migration():
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0066_storage_cleanup_jobs.py"
    )
    spec = importlib.util.spec_from_file_location("storage_cleanup_migration", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"alembic": SimpleNamespace(op=MagicMock())}):
        spec.loader.exec_module(module)
    return module


def test_storage_cleanup_migration_is_linear_and_matches_model_indexes() -> None:
    migration = _load_migration()
    assert migration.revision == "0066_storage_cleanup_jobs"
    assert migration.down_revision == "0065_ai_travel_inbox"

    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    migration_indexes = {
        call.args[0]: tuple(call.args[2])
        for call in operation_proxy.create_index.call_args_list
        if call.args[1] == "storage_cleanup_jobs"
    }
    model_indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in StorageCleanupJobModel.__table__.indexes
    }
    assert migration_indexes == model_indexes
    assert migration_indexes["ix_storage_cleanup_jobs_due"] == (
        "status",
        "next_attempt_at",
        "created_at",
    )
    assert migration_indexes["ix_storage_cleanup_jobs_expired_lease"] == (
        "status",
        "lease_expires_at",
    )

    operation_proxy.reset_mock()
    with patch.object(migration, "op", operation_proxy):
        migration.downgrade()
    operation_proxy.drop_table.assert_called_once_with("storage_cleanup_jobs")
