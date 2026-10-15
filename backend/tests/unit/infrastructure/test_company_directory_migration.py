"""The company backfill suppresses only its known roster trigger, transactionally."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def migration(monkeypatch):
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0130_company_directory.py"
    spec = importlib.util.spec_from_file_location("company_directory_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    operations = Mock()
    operations.get_bind.return_value.scalar.return_value = True
    monkeypatch.setattr(module, "op", operations)
    return module, operations


def test_backfill_requires_exact_trigger_and_restores_it_before_later_ddl(migration):
    module, operations = migration
    module.upgrade()
    query = str(operations.get_bind.return_value.scalar.call_args.args[0])
    for condition in (
        "tgrelid = 'public.client_groups'::regclass", "tgname = 'group_roster_revision'",
        "NOT tgisinternal", "tgenabled = 'O'", "tgtype = 19", "tgnargs = 0",
        "tgqual IS NULL", "tgattr::text = ''",
        "tgfoid = 'public.bump_group_roster_revision()'::regprocedure",
    ):
        assert condition in query
    statements = [str(call.args[0]).strip() for call in operations.execute.call_args_list]
    assert len(statements) == 4
    assert statements[0] == "SET LOCAL lock_timeout = '5s'"
    assert statements[1] == "ALTER TABLE public.client_groups DISABLE TRIGGER group_roster_revision"
    assert statements[2].startswith("UPDATE client_groups AS g SET company_id")
    assert "roster_revision" not in statements[2]
    assert statements[3] == "ALTER TABLE public.client_groups ENABLE TRIGGER group_roster_revision"
    calls = operations.mock_calls
    disable = next(index for index, call in enumerate(calls) if call[0] == "execute" and "DISABLE" in str(call.args[0]))
    enable = next(index for index, call in enumerate(calls) if call[0] == "execute" and "ENABLE" in str(call.args[0]))
    assert all(index < disable for index, call in enumerate(calls) if call[0] == "add_column")
    assert all(index > enable for index, call in enumerate(calls) if call[0] == "create_index")


@pytest.mark.parametrize("signature_matches", [False, None, 1])
def test_unexpected_trigger_fails_without_disable_or_backfill(migration, signature_matches):
    module, operations = migration
    operations.get_bind.return_value.scalar.return_value = signature_matches
    with pytest.raises(RuntimeError, match="Expected enabled group roster trigger"):
        module._backfill_company_scope()
    operations.execute.assert_not_called()


def test_backfill_error_propagates_for_transaction_rollback_without_new_sql(migration):
    module, operations = migration
    operations.execute.side_effect = [None, RuntimeError("synthetic database failure")]
    with pytest.raises(RuntimeError, match="synthetic database failure"):
        module._backfill_company_scope()
    assert operations.execute.call_count == 2
    assert "DISABLE TRIGGER group_roster_revision" in operations.execute.call_args_list[0].args[0]
    assert operations.execute.call_args_list[1].args[0].lstrip().startswith("UPDATE client_groups")
