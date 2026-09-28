"""The additive flag migration preserves existing documents and review data."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def migration_module():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0113_document_follow_up.py"
    spec = importlib.util.spec_from_file_location("document_follow_up_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_adds_false_default_without_rewriting_or_deleting_rows():
    migration = migration_module()
    operation = MagicMock()
    with patch.object(migration, "op", operation):
        migration.upgrade()
    assert migration.down_revision == "0112_passport_cover_edits"
    table, column = operation.add_column.call_args.args
    assert table == "passport_submissions" and column.name == "document_follow_up"
    assert column.nullable is False and str(column.server_default.arg) == "false"
    operation.execute.assert_called_once_with("SET LOCAL lock_timeout = '5s'")
    operation.drop_column.assert_not_called()


@pytest.mark.parametrize("flagged", [True, False])
def test_downgrade_cannot_discard_active_follow_up_work(flagged):
    migration = migration_module()
    operation = MagicMock()
    operation.get_bind.return_value.execute.return_value.scalar_one.return_value = flagged
    with patch.object(migration, "op", operation):
        if flagged:
            with pytest.raises(RuntimeError, match="preserve"):
                migration.downgrade()
            operation.drop_column.assert_not_called()
        else:
            migration.downgrade()
            operation.drop_column.assert_called_once_with("passport_submissions", "document_follow_up")
