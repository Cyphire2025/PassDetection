"""Complete authority retention and exact empty-table/runtime-privilege gates."""

import copy
import hashlib
from unittest.mock import MagicMock

import pytest

from scripts import mcp_dashboard_write_schema as catalog_source
from scripts import release_travel_tracker_upgrade as helper


def test_retained_catalog_keeps_every_existing_permission_and_delivery_field():
    old = {
        "mcp_control": {
            "columns": [["write_enabled", "boolean"], ["allowed_write_tools", "jsonb"]]
        },
        "mcp_grants": {
            "columns": [["permission_revision", "integer"], ["allowed_read_sections", "jsonb"]]
        },
        "mcp_native_transfers": {"columns": [["purpose", "text"]]},
        "mcp_document_delivery_outbox": {"columns": [["status", "text"]]},
    }
    value = {**copy.deepcopy(old), "travel_tracker": {}, "alembic_version": {}}
    assert helper.retained_catalog(value) == old


def test_authority_hash_includes_all_old_fields_and_closes_stream():
    connection = MagicMock()
    connection.dialect.identifier_preparer.quote_identifier.side_effect = lambda name: f'"{name}"'
    rows = MagicMock()
    original = '{"id":1,"write_enabled":true,"updated_at":"2026-01-01"}'
    rows.__iter__.return_value = iter([(original,)])
    connection.execute.return_value = rows
    result = helper.authority_snapshot(connection, ["mcp_control"])
    assert result == {
        "mcp_control": {
            "count": 1,
            "sha256": hashlib.sha256((original + "\n").encode()).hexdigest(),
        }
    }
    statement = str(connection.execute.call_args.args[0])
    assert "to_jsonb(record)::text" in statement and 'public."mcp_control"' in statement
    assert "excluded" not in statement
    rows.close.assert_called_once()


def test_source_refuses_an_unreviewed_tracker_table(monkeypatch):
    monkeypatch.setattr(catalog_source, "catalog", lambda _: {"travel_tracker": {}})
    with pytest.raises(ValueError, match="unreviewed_tracker"):
        helper.verify_schema(MagicMock(), helper.SOURCE)


@pytest.mark.parametrize("drift", ["default", "foreign_key", "index", "rls", "trigger"])
def test_target_schema_rejects_every_unreviewed_structural_change(monkeypatch, drift):
    table = copy.deepcopy(helper.expected_tracker_catalog())
    if drift == "default":
        next(row for row in table["columns"] if row[0] == "visa_applied")[4] = "true"
    elif drift == "foreign_key":
        table["constraints"].pop()
    elif drift == "index":
        table["indexes"][0][1] = False
    elif drift == "rls":
        table["relation"][1] = True
    else:
        table["triggers"] = [["unreviewed", "O", "CREATE TRIGGER unreviewed"]]
    monkeypatch.setattr(catalog_source, "catalog", lambda _: {"travel_tracker": table})
    with pytest.raises(ValueError, match="schema_mismatch"):
        helper.verify_schema(MagicMock(), helper.TARGET)


def test_target_requires_empty_table_and_existing_runtime_dml(monkeypatch):
    actual = {"travel_tracker": helper.expected_tracker_catalog()}
    monkeypatch.setattr(catalog_source, "catalog", lambda _: actual)
    connection = MagicMock()
    connection.execute.return_value.scalar_one.return_value = True
    with pytest.raises(ValueError, match="empty_before_activation"):
        helper.verify_schema(connection, helper.TARGET)
    connection.execute.return_value.scalar_one.return_value = False
    monkeypatch.setattr(
        helper,
        "_dml_grants",
        lambda _, name: {(123, "SELECT", False)} if name == "passport_submissions" else set(),
    )
    with pytest.raises(ValueError, match="runtime_privileges_missing"):
        helper.verify_schema(connection, helper.TARGET)
    monkeypatch.setattr(helper, "_dml_grants", lambda _, name: {(123, "SELECT", False)})
    assert helper.verify_schema(connection, helper.TARGET) == actual
