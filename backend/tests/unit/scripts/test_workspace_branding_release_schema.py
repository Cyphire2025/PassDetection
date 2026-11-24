"""Baseline-aware preservation of existing branding and new private columns."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts import workspace_branding_release_schema as schema
from scripts.workspace_branding_release import CHAIN, SOURCE, TARGET


def catalog_at(checkpoint):
    tables = {name: {"columns": [["id", "uuid"]]} for name in schema.ADDITIONS}
    if checkpoint != SOURCE:
        for table, additions in schema.ADDITIONS.items():
            for revision, column in additions:
                if CHAIN.index(revision) <= CHAIN.index(checkpoint):
                    tables[table]["columns"].append(list(column))
    return tables


@pytest.mark.parametrize("checkpoint", [SOURCE, *CHAIN])
def test_original_baseline_normalizes_only_reviewed_additions(monkeypatch, checkpoint):
    connection = MagicMock()
    connection.scalar.return_value = False
    monkeypatch.setattr(schema, "catalog", lambda _: catalog_at(checkpoint))
    assert schema.verify_schema(connection, Path("unused"), checkpoint) == catalog_at(SOURCE)


def test_existing_branding_is_retained_in_the_background_only_baseline(monkeypatch):
    connection = MagicMock()
    connection.dialect.identifier_preparer.quote_identifier = lambda value: '"' + value + '"'
    connection.scalar.side_effect = lambda query: '"background_image_key"' not in str(query)
    monkeypatch.setattr(schema, "catalog", lambda _: catalog_at(TARGET))
    assert schema.verify_schema(connection, Path("unused"), TARGET, CHAIN[0]) == catalog_at(CHAIN[0])


def test_background_write_before_activation_fails_closed(monkeypatch):
    connection = MagicMock()
    connection.scalar.return_value = True
    monkeypatch.setattr(schema, "catalog", lambda _: catalog_at(TARGET))
    with pytest.raises(ValueError, match="must_remain_null"):
        schema.verify_schema(connection, Path("unused"), TARGET, CHAIN[0])


def test_changed_background_column_definition_is_rejected(monkeypatch):
    changed = deepcopy(catalog_at(TARGET))
    changed["client_groups"]["columns"][-1][2] = "NO"
    monkeypatch.setattr(schema, "catalog", lambda _: changed)
    with pytest.raises(ValueError, match="column_checkpoint_changed"):
        schema.verify_schema(MagicMock(), Path("unused"), TARGET, CHAIN[0])


def test_existing_column_grants_are_preserved_but_new_background_grants_are_rejected():
    connection = MagicMock()
    rows = [("banner_image_key", "existing-acl"), ("background_image_key", None)]
    connection.execute.return_value.all.return_value = rows
    assert schema.column_acl_snapshot(connection, {"client_groups": {}}, CHAIN[0]) == {
        "client_groups": [["banner_image_key", "existing-acl"]],
    }
    connection.execute.return_value.all.return_value = [*rows[:-1], ("background_image_key", "expanded-acl")]
    with pytest.raises(ValueError, match="column_grants_forbidden"):
        schema.column_acl_snapshot(connection, {"client_groups": {}}, CHAIN[0])
