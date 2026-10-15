from __future__ import annotations

import copy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts import document_distribution_release as policy
from scripts import document_distribution_release_schema as schema

BACKEND = Path(__file__).resolve().parents[3]


def test_exact_contract_and_forward_only_revisions():
    entries = policy.migration_entries(BACKEND)
    contract = {**policy.POLICY, "migrations": entries}
    policy.verify_sources(BACKEND, contract)
    assert policy.remaining_revisions(policy.SOURCE) == policy.CHAIN
    assert policy.remaining_revisions(policy.CHAIN[0]) == (policy.TARGET,)
    assert policy.remaining_revisions(policy.TARGET) == ()
    with pytest.raises(ValueError, match="source_schema_mismatch"):
        policy.remaining_revisions("0137_company_directory")


@pytest.mark.parametrize("change", [
    lambda value: value.update(automatic_downgrade=True),
    lambda value: value.update(automatic_downgrade=0),
    lambda value: value.update(new_columns="any"),
    lambda value: value.update(resume_schema_revisions=[policy.SOURCE]),
    lambda value: value.update(unreviewed=True),
    lambda value: value["migrations"].reverse(),
    lambda value: value["migrations"][0].update(sha256="A" * 64),
])
def test_contract_rejects_policy_or_chain_changes(change):
    value = {**copy.deepcopy(policy.POLICY), "migrations": policy.migration_entries(BACKEND)}
    change(value)
    with pytest.raises(ValueError):
        policy.validate_contract(value, policy.TARGET)


@pytest.mark.parametrize("replacement", [
    lambda value: value + "\nprint('extra side effect')\n",
    lambda value: value.replace("nullable=True", "nullable=False"),
    lambda value: value.replace("nullable=True", "nullable=True, server_default='label'"),
    lambda value: value.replace("sa.String(255)", "sa.String(512)"),
    lambda value: value.replace("SET LOCAL lock_timeout = '5s'", "SET LOCAL lock_timeout = '0'"),
    lambda value: value.replace('op.drop_column("passport_submissions", "display_name")', 'op.drop_table("passport_submissions")'),
])
def test_extra_migration_effects_rejected_before_source_binding(tmp_path, replacement):
    target = tmp_path / "alembic/versions"
    target.mkdir(parents=True)
    for revision in policy.CHAIN:
        raw = (BACKEND / "alembic/versions" / f"{revision}.py").read_text()
        (target / f"{revision}.py").write_text(replacement(raw) if revision == policy.CHAIN[0] else raw)
    with pytest.raises(ValueError, match="exact_document_migration_source_required"):
        policy.migration_entries(tmp_path)


def checkpoint_catalog(revision):
    actual = {}
    for table, (added, column) in schema.ADDITIONS.items():
        columns = [["id", "uuid", "NO", None, None, "NO", "NEVER"]]
        if revision != policy.SOURCE and policy.CHAIN.index(revision) >= policy.CHAIN.index(added):
            columns.append(column.copy())
        actual[table] = {"columns": columns, "constraints": [], "indexes": [], "triggers": []}
    actual["alembic_version"] = {"columns": []}
    return actual


@pytest.mark.parametrize("revision", [policy.SOURCE, *policy.CHAIN])
def test_exact_nullable_checkpoint_normalizes_only_added_columns(monkeypatch, revision):
    connection = MagicMock()
    connection.scalar.return_value = False
    actual = checkpoint_catalog(revision)
    monkeypatch.setattr(schema, "catalog", lambda _: actual)
    assert schema.verify_schema(connection, BACKEND, revision) == schema.retained_catalog(checkpoint_catalog(policy.SOURCE))


@pytest.mark.parametrize("mutation", [
    lambda actual: actual["passport_submissions"]["columns"][-1].__setitem__(2, "NO"),
    lambda actual: actual["passport_submissions"]["columns"][-1].__setitem__(3, 512),
    lambda actual: actual["whatsapp_message_logs"]["columns"][-1].__setitem__(4, "'{}'::jsonb"),
])
def test_wrong_column_shape_rejected(monkeypatch, mutation):
    actual = checkpoint_catalog(policy.TARGET)
    mutation(actual)
    monkeypatch.setattr(schema, "catalog", lambda _: actual)
    connection = MagicMock()
    connection.scalar.return_value = False
    with pytest.raises(ValueError, match="document_column_checkpoint_changed"):
        schema.verify_schema(connection, BACKEND, policy.TARGET)


def test_pre_activation_values_and_new_column_grants_rejected(monkeypatch):
    actual = checkpoint_catalog(policy.TARGET)
    monkeypatch.setattr(schema, "catalog", lambda _: actual)
    connection = MagicMock()
    connection.scalar.return_value = True
    with pytest.raises(ValueError, match="must_remain_null"):
        schema.verify_schema(connection, BACKEND, policy.TARGET)
    connection.execute.return_value.all.return_value = [("display_name", "{unexpected=r/owner}")]
    with pytest.raises(ValueError, match="column_grants_forbidden"):
        schema.column_acl_snapshot(connection, {"passport_submissions": {}})


def test_unrelated_catalog_changes_remain_in_digest():
    original = checkpoint_catalog(policy.SOURCE)
    changed = copy.deepcopy(original)
    changed["passport_submissions"]["triggers"].append(["altered", "O", "changed"])
    assert schema.retained_catalog(changed) != schema.retained_catalog(original)
