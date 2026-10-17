"""A resumed helper must retain the original pre-DDL preservation baseline."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, Mock

import pytest

from scripts import release_workspace_branding_upgrade as helper
from scripts.workspace_branding_release import (
    CHAIN,
    POLICY,
    SOURCE,
    TARGET,
    migration_entries,
)


def contract():
    return {**POLICY, "migrations": migration_entries(helper.ROOT)}


@pytest.fixture
def database(monkeypatch, test_settings):
    state = {"schema": SOURCE, "owner": True,
        "snapshot": {"rows": {"legacy": "original"}, "acl": [], "catalog": {}}}
    connection, engine = MagicMock(), MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    connection.execute.side_effect = lambda statement: Mock(
        scalar_one=Mock(return_value=state["owner"] if "current_user=" in str(statement) else state["schema"]))
    monkeypatch.setattr("sqlalchemy.create_engine", Mock(return_value=engine))
    monkeypatch.setattr("app.core.config.settings.get_settings", lambda: test_settings)
    monkeypatch.setattr("alembic.script.ScriptDirectory.from_config",
        lambda _: Mock(get_heads=lambda: [TARGET]))
    monkeypatch.setattr("scripts.workspace_branding_release_schema.preservation_snapshot",
        lambda *_: state["snapshot"])
    monkeypatch.setattr("scripts.workspace_branding_release_schema.verify_schema", Mock())
    upgrade = Mock(side_effect=lambda _config, revision: state.update(schema=revision))
    monkeypatch.setattr("alembic.command.upgrade", upgrade)
    monkeypatch.setenv("MCP_RELEASE_PROOF_SHA256", "a" * 64)
    monkeypatch.setenv("MCP_RELEASE_BASELINE_SHA256", helper.preservation_digest(state["snapshot"]))
    return state, upgrade, engine


@pytest.mark.parametrize("value", [None, "", "a" * 63, "A" * 64])
def test_missing_or_invalid_original_baseline_fails_before_database(monkeypatch, database, value):
    _, upgrade, engine = database
    if value is None:
        monkeypatch.delenv("MCP_RELEASE_BASELINE_SHA256")
    else:
        monkeypatch.setenv("MCP_RELEASE_BASELINE_SHA256", value)
    with pytest.raises(ValueError, match="original_preservation_baseline_required"):
        helper.apply_upgrade(contract())
    engine.connect.assert_not_called()
    upgrade.assert_not_called()


def test_baseline_capture_is_source_only_and_never_runs_ddl(database):
    state, upgrade, _ = database
    receipt = helper.apply_upgrade(contract(), capture_baseline=True)
    assert receipt["status"] == "baseline_captured"
    assert receipt["preservation_sha256"] == helper.preservation_digest(state["snapshot"])
    assert receipt["release_proof_sha256"] == "a" * 64
    state["schema"] = CHAIN[0]
    with pytest.raises(ValueError, match="original_source_required_for_baseline"):
        helper.apply_upgrade(contract(), capture_baseline=True)
    upgrade.assert_not_called()


@pytest.mark.parametrize("capture", [False, True])
def test_non_owner_cannot_capture_or_apply(database, capture):
    state, upgrade, _ = database
    state["owner"] = False
    with pytest.raises(ValueError, match="existing_migration_identity_required"):
        helper.apply_upgrade(contract(), capture_baseline=capture)
    upgrade.assert_not_called()


@pytest.mark.parametrize("schema", [SOURCE, *CHAIN])
def test_changed_original_baseline_blocks_every_resume_before_ddl(database, schema):
    state, upgrade, _ = database
    state.update(schema=schema, snapshot={"rows": {"legacy": "changed"}})
    with pytest.raises(ValueError, match="original_historical_rows"):
        helper.apply_upgrade(contract())
    upgrade.assert_not_called()


@pytest.mark.parametrize("schema", [SOURCE, CHAIN[0], TARGET])
def test_source_partial_and_target_validation_share_exact_original_baseline(database, schema):
    state, upgrade, _ = database
    state["schema"] = schema
    receipt = helper.apply_upgrade(contract())
    assert receipt["preservation_sha256"] == helper.preservation_digest(state["snapshot"])
    assert receipt["executed_revisions"] == list(helper.remaining_revisions(schema))
    assert upgrade.call_count == len(helper.remaining_revisions(schema))
    assert receipt["runtime_grants_verified"] is True


def test_mutation_during_committed_upgrade_fails_final_validation(database):
    state, upgrade, _ = database
    def change(_config, revision):
        state.update(schema=revision)
        if revision == TARGET:
            state["snapshot"] = {"rows": {"legacy": "changed after commit"}}
    upgrade.side_effect = change
    with pytest.raises(ValueError, match="original_historical_rows"):
        helper.apply_upgrade(contract())
    assert state["schema"] == TARGET


@pytest.mark.parametrize("key", ["catalog", "acl", "column_acl"])
def test_changed_catalog_or_grant_blocks_resume(database, key):
    state, upgrade, _ = database
    state["schema"] = CHAIN[0]
    state["snapshot"] = {**state["snapshot"], key: ["unreviewed change"]}
    with pytest.raises(ValueError, match="original_historical_rows"):
        helper.apply_upgrade(contract())
    upgrade.assert_not_called()


def test_committed_revision_checkpoint_mismatch_stops_forward_execution(database):
    state, upgrade, _ = database
    upgrade.side_effect = lambda *_: None
    with pytest.raises(ValueError, match="migration_checkpoint_mismatch"):
        helper.apply_upgrade(contract())
    assert upgrade.call_count == 1
    assert state["schema"] == SOURCE


def test_cli_failure_never_exposes_snapshot_or_credentials(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["upgrade", "--contract-json", json.dumps(contract())])
    monkeypatch.setattr(helper, "apply_upgrade", Mock(side_effect=ValueError("private password record")))
    assert helper.main() == 2
    assert json.loads(capsys.readouterr().out) == {"status": "failed",
        "reason": "workspace_branding_upgrade_failed", "automatic_downgrade": False}
