"""Interrupted concurrent index builds recover without deleting valid indexes."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def migration(monkeypatch, existing):
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0132_traveller_source_seek.py"
    spec = importlib.util.spec_from_file_location("traveller_seek_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    operations = MagicMock()
    operations.get_bind.return_value.execute.return_value.mappings.return_value.first.return_value = existing
    monkeypatch.setattr(module, "op", operations)
    return module, operations


def test_invalid_interrupted_index_is_rebuilt_concurrently(monkeypatch):
    module, operations = migration(monkeypatch, {"indisvalid": False, "definition": "interrupted"})
    module._ensure_index(module.INDEX_NAME, "passport_submissions", "agency_id, group_id, id")
    assert [call.args[0] for call in operations.execute.call_args_list] == [
        "DROP INDEX CONCURRENTLY ix_passport_submissions_scoped_seek",
        "CREATE INDEX CONCURRENTLY ix_passport_submissions_scoped_seek ON passport_submissions (agency_id, group_id, id)"]


def test_valid_expected_index_is_idempotent(monkeypatch):
    module, operations = migration(monkeypatch, {"indisvalid": True,
        "definition": "CREATE INDEX ix_passport_submissions_scoped_seek ON public.passport_submissions USING btree (agency_id, group_id, id)"})
    module._ensure_index(module.INDEX_NAME, "passport_submissions", "agency_id, group_id, id")
    operations.execute.assert_not_called()


def test_unexpected_valid_index_is_not_overwritten(monkeypatch):
    module, operations = migration(monkeypatch, {"indisvalid": True, "definition": "another indexed table"})
    with pytest.raises(RuntimeError, match="unexpected definition"):
        module._ensure_index(module.INDEX_NAME, "passport_submissions", "agency_id, group_id, id")
    operations.execute.assert_not_called()
