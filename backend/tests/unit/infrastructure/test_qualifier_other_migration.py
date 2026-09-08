from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations


def migration():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0091_qualifier_other_relation.py"
    spec = importlib.util.spec_from_file_location("qualifier_other_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_compiles_postgresql_ddl_without_changing_stored_settings_or_answers():
    module = migration()
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with patch.object(module, "op", Operations(context)):
        module.upgrade()
    ddl = output.getvalue()
    assert module.down_revision == "0090_upload_configuration"
    assert ddl.count("TYPE VARCHAR(100)") == 2
    assert ddl.count("'other'") == 4
    assert "'legal_guardian'" in ddl
    assert "UPDATE " not in ddl
    assert "DELETE " not in ddl
    assert "ck_qualifier_selections_other_text" in ddl
    assert "ck_passport_submissions_qualifier_other_text" in ddl


def test_downgrade_refuses_to_destroy_custom_or_long_answers_before_ddl():
    module = migration()
    operations = MagicMock()
    operations.get_bind.return_value.execute.return_value.scalar.return_value = True
    with patch.object(module, "op", operations), pytest.raises(RuntimeError, match="custom qualifier"):
        module.downgrade()
    operations.drop_constraint.assert_not_called()
    operations.alter_column.assert_not_called()


def test_legacy_only_database_can_downgrade_after_both_tables_are_checked():
    module = migration()
    operations = MagicMock()
    operations.get_bind.return_value.execute.return_value.scalar.return_value = False
    with patch.object(module, "op", operations):
        module.downgrade()
    assert operations.get_bind.return_value.execute.call_count == 2
    assert operations.alter_column.call_count == 2
    for call in operations.create_check_constraint.call_args_list:
        assert "'other'" not in call.args[2]
