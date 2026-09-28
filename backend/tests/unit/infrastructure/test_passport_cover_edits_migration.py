import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def migration_module():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0112_passport_cover_edits.py"
    spec = importlib.util.spec_from_file_location("cover_edits_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_expands_both_constraints_without_rewriting_records():
    migration = migration_module()
    operation = MagicMock()
    with patch.object(migration, "op", operation):
        migration.upgrade()
    assert migration.down_revision == "0111_roster_revision"
    assert operation.create_check_constraint.call_count == 2
    for call in operation.create_check_constraint.call_args_list:
        assert "'passport_cover', 'passport_back_cover'" in call.args[2]
        assert "'visa_photo', 'passport_front', 'passport_back'" in call.args[2]
    operation.execute.assert_called_once_with("SET LOCAL lock_timeout = '5s'")
    operation.drop_table.assert_not_called()
    operation.drop_column.assert_not_called()


@pytest.mark.parametrize("covers_in_table", [0, 1])
def test_downgrade_preserves_existing_cover_history(covers_in_table):
    migration = migration_module()
    operation = MagicMock()
    operation.get_bind.return_value.execute.return_value.scalar_one.side_effect = (
        [True] if covers_in_table == 0 else [False, True]
    )
    with patch.object(migration, "op", operation), pytest.raises(RuntimeError, match="preserve"):
        migration.downgrade()
    operation.drop_constraint.assert_not_called()
    operation.create_check_constraint.assert_not_called()


def test_downgrade_without_cover_history_restores_original_constraints():
    migration = migration_module()
    operation = MagicMock()
    operation.get_bind.return_value.execute.return_value.scalar_one.return_value = False
    with patch.object(migration, "op", operation):
        migration.downgrade()
    assert operation.create_check_constraint.call_count == 2
    for call in operation.create_check_constraint.call_args_list:
        assert "passport_cover" not in call.args[2]
