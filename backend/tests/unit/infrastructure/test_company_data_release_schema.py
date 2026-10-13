"""Narrow catalog normalization never exempts existing row fields or tenant FKs."""
import copy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts import companies_traveller_release_schema as schema
from scripts.companies_traveller_reuse_release import CHAIN, SOURCE


def manager_catalog(target=False):
    return {schema.MANAGER_TABLE: {
        "columns": [["organization_id", "uuid", "YES" if target else "NO", None, None, "NO", "NEVER"]],
        "constraints": [[name, "c" if name.startswith("ck_") else "f", True, False, False, definition]
            for name, definition in schema.MANAGER_CONSTRAINTS.items()] if target else [],
        "indexes": [], "triggers": [], "relation": ["r", False, False, "p"],
    }}


def test_manager_nullability_and_independent_tenant_constraints_are_one_checkpoint():
    old, new = manager_catalog(), manager_catalog(True)
    schema.verify_manager_checkpoint(old, SOURCE)
    schema.verify_manager_checkpoint(old, CHAIN[0])
    schema.verify_manager_checkpoint(new, CHAIN[1])
    assert schema.retained_catalog(old, set()) == schema.retained_catalog(new, set())
    assert new[schema.MANAGER_TABLE]["columns"][0][2] == "YES"  # No mutation of evidence.
    for actual, checkpoint in [(old, CHAIN[1]), (new, SOURCE), (new, CHAIN[0])]:
        with pytest.raises(ValueError):
            schema.verify_manager_checkpoint(actual, checkpoint)


@pytest.mark.parametrize("change", ["drop_fk", "unvalidated", "deferrable", "wrong_tenant", "weaker_check"])
def test_manager_target_rejects_weakened_scope(change):
    actual = manager_catalog(True)
    rows = actual[schema.MANAGER_TABLE]["constraints"]
    if change == "drop_fk":
        rows.pop(0)
    elif change == "unvalidated":
        rows[0][2] = False
    elif change == "deferrable":
        rows[0][3] = True
    elif change == "wrong_tenant":
        rows[0][-1] = rows[0][-1].replace("agency_id", "group_id")
    else:
        rows[-1][-1] += " OR true"
    with pytest.raises(ValueError):
        schema.verify_manager_checkpoint(actual, CHAIN[1])


def test_only_exact_new_catalog_fields_are_normalized():
    old = manager_catalog()
    changed = copy.deepcopy(old)
    changed[schema.MANAGER_TABLE]["columns"][0][1] = "text"
    assert schema.retained_catalog(old, set()) != schema.retained_catalog(changed, set())
    changed = copy.deepcopy(old)
    changed[schema.MANAGER_TABLE]["constraints"].append(["existing_scope", "f", False])
    assert schema.retained_catalog(old, set()) != schema.retained_catalog(changed, set())


def test_new_tables_are_exact_and_present_from_first_revision():
    backend = Path(__file__).resolve().parents[3]
    assert schema.new_tables(backend, SOURCE) == set()
    expected = {"company_data_export_jobs", "company_data_export_parts"}
    assert schema.new_tables(backend, CHAIN[0]) == expected
    assert schema.new_tables(backend, CHAIN[1]) == expected


def test_row_hash_includes_all_original_company_fields_and_streams():
    connection = MagicMock()
    connection.dialect.identifier_preparer.quote_identifier.side_effect = lambda name: f'"{name}"'
    rows = MagicMock()
    rows.__iter__.return_value = iter([('{"organization_id":"original","is_active":true}',)])
    connection.execute.return_value = rows
    result = schema.authority_snapshot(connection, manager_catalog())
    statement = connection.execute.call_args.args[0]
    assert "to_jsonb(record))::text" in str(statement) and "excluded" not in str(statement)
    assert statement.get_execution_options()["yield_per"] == 100
    assert result[schema.MANAGER_TABLE]["count"] == 1
    rows.close.assert_called_once()


def test_source_date_projection_has_exact_shape_and_no_retained_field_exemptions():
    table = {"traveller_match_cases": {"columns": [], "indexes": [], "constraints": []}}
    connection = MagicMock()
    schema.verify_source_projection(connection, table, SOURCE)
    table["traveller_match_cases"]["columns"] = [[schema.SOURCE_PROJECTION,
        "timestamp with time zone", "YES", None, None, "NO", "NEVER"]]
    connection.scalar.return_value = False
    schema.verify_source_projection(connection, table, CHAIN[0])
    assert "s.agency_id = c.agency_id AND s.group_id = c.group_id" in str(connection.scalar.call_args.args[0])
    assert schema.retained_catalog(table, set())["traveller_match_cases"]["columns"] == []
    connection.scalar.return_value = True
    with pytest.raises(ValueError, match="backfill"):
        schema.verify_source_projection(connection, table, CHAIN[1])
    with pytest.raises(ValueError, match="at_source"):
        schema.verify_source_projection(connection, table, SOURCE)
