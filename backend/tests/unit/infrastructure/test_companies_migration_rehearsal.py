"""Guard the destructive CI scope and exercise forward-resume assertions."""

import re
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg2
import pytest

from scripts import rehearse_companies_traveller_upgrade as rehearsal
from scripts.companies_rehearsal_fixture import (
    create_interrupted_source_index,
    seed_company_and_roster,
)


def test_populated_seed_inserts_only_actual_model_columns():
    from app.infrastructure.database.models import Base

    connection, cursor = Mock(), Mock()
    connection.cursor.return_value.__enter__ = Mock(return_value=cursor)
    connection.cursor.return_value.__exit__ = Mock(return_value=False)
    seed_company_and_roster(connection)
    statement = cursor.execute.call_args.args[0]
    inserts = re.findall(r"INSERT INTO (\w+)\s*\(([^)]+)\)", statement)
    assert len(inserts) == 6
    for table_name, raw_columns in inserts:
        supplied = {column.strip() for column in raw_columns.split(",")}
        unknown = supplied - set(Base.metadata.tables[table_name].columns.keys())
        assert not unknown, f"{table_name} seed names nonexistent columns: {unknown}"
    connection.commit.assert_called_once()


def environment(**changes):
    return {"POSTGRES_HOST": "localhost", "POSTGRES_DB": "test_db",
        "MIGRATION_REHEARSAL_ALLOW_EPHEMERAL_DATABASE_DELETION": "1", **changes}


@pytest.mark.parametrize("changes", [
    {"POSTGRES_HOST": "database.production.invalid"},
    {"POSTGRES_DB": rehearsal.SOURCE_DATABASE},
    {"POSTGRES_DB": rehearsal.RESTORED_DATABASE},
    {"MIGRATION_REHEARSAL_ALLOW_EPHEMERAL_DATABASE_DELETION": "0"},
])
def test_rehearsal_refuses_non_ephemeral_scope(changes):
    with pytest.raises((ValueError, RuntimeError)):
        rehearsal.validate_environment(environment(**changes))


def test_loopback_scope_has_distinct_exact_databases():
    rehearsal.validate_environment(environment())
    assert rehearsal.SOURCE_DATABASE != rehearsal.RESTORED_DATABASE
    assert rehearsal.SOURCE_DATABASE.startswith("passdetection_ci_")
    assert rehearsal.RESTORED_DATABASE.startswith("passdetection_ci_")


def test_unrelated_helper_failure_cannot_count_as_planned_interruption(monkeypatch):
    monkeypatch.setattr(rehearsal.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=2)))
    with pytest.raises(RuntimeError, match="expected exit 73"):
        rehearsal.run_helper(environment(), {}, interrupt=True)


def test_resume_exercises_actual_checkpoint_then_noop(monkeypatch):
    connection, before = Mock(), {"rows": {"synthetic": 700}}
    baseline = rehearsal.preservation_digest(before)
    runner = Mock(side_effect=[{"exit_code": 74, "rolled_back_revision": rehearsal.CHAIN[0]},
        {"status": "baseline_captured", "preservation_sha256": baseline}, {"exit_code": 73},
        {"status": "failed"},
        {"started_schema": rehearsal.CHAIN[1], "executed_revisions": list(rehearsal.CHAIN[2:])},
        {"status": "already_at_target", "executed_revisions": []}])
    invalid_index = Mock()
    monkeypatch.setattr(rehearsal, "run_helper", runner)
    monkeypatch.setattr(rehearsal, "_connect", Mock(return_value=connection))
    monkeypatch.setattr(rehearsal, "_revision", Mock(side_effect=[rehearsal.SOURCE, rehearsal.CHAIN[1], rehearsal.CHAIN[1]]))
    monkeypatch.setattr(rehearsal, "create_interrupted_source_index", invalid_index)
    monkeypatch.setattr(rehearsal, "snapshot", Mock(return_value=before))
    result = rehearsal.exercise_resume(environment(), {}, before)
    assert runner.call_count == 6
    assert runner.call_args_list[0].kwargs == {"rollback_backfill": True, "baseline_sha256": baseline}
    assert runner.call_args_list[1].kwargs == {"capture_baseline": True}
    assert runner.call_args_list[2].kwargs == {"interrupt": True, "baseline_sha256": baseline}
    assert runner.call_args_list[3].kwargs == {"baseline_sha256": "0" * 64, "expect_rejection": True}
    assert all(call.kwargs["baseline_sha256"] == baseline for call in runner.call_args_list[4:])
    invalid_index.assert_called_once_with(connection)
    assert connection.close.call_count == 3
    assert result["company_backfill_rollback_verified"] is True
    assert result["invalid_concurrent_index_repaired"] is True
    assert result["wrong_baseline_rejected_before_ddl"] is True


def test_resume_rejects_historical_mutation_before_continuing(monkeypatch):
    runner = Mock(side_effect=[{"exit_code": 74}, {"status": "baseline_captured",
        "preservation_sha256": rehearsal.preservation_digest({"rows": "original"})}, {"exit_code": 73}])
    monkeypatch.setattr(rehearsal, "run_helper", runner)
    monkeypatch.setattr(rehearsal, "_connect", Mock(return_value=Mock()))
    monkeypatch.setattr(rehearsal, "_revision", Mock(side_effect=[rehearsal.SOURCE, rehearsal.CHAIN[1]]))
    monkeypatch.setattr(rehearsal, "create_interrupted_source_index", Mock())
    monkeypatch.setattr(rehearsal, "snapshot", Mock(side_effect=[{"rows": "original"}, {"rows": "changed"}]))
    with pytest.raises(AssertionError, match="changed historical"):
        rehearsal.exercise_resume(environment(), {}, {"rows": "original"})
    assert runner.call_count == 3


@pytest.mark.parametrize("changed_schema", [False, True])
def test_failed_backfill_must_restore_original_schema_rows_and_trigger(monkeypatch, changed_schema):
    runner = Mock(return_value={"exit_code": 74})
    monkeypatch.setattr(rehearsal, "run_helper", runner)
    monkeypatch.setattr(rehearsal, "_connect", Mock(return_value=Mock()))
    monkeypatch.setattr(rehearsal, "_revision", Mock(return_value=rehearsal.CHAIN[0] if changed_schema else rehearsal.SOURCE))
    monkeypatch.setattr(rehearsal, "snapshot", Mock(return_value={"catalog": "trigger disabled"}))
    with pytest.raises(AssertionError, match="Backfill"):
        rehearsal.exercise_resume(environment(), {}, {"catalog": "trigger enabled"})
    assert runner.call_count == 1  # Never capture a new baseline after failed rollback.


def test_unrelated_failure_is_not_accepted_as_backfill_rollback(monkeypatch):
    monkeypatch.setattr(rehearsal.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=2)))
    with pytest.raises(RuntimeError, match="expected exit 74"):
        rehearsal.run_helper(environment(), {}, rollback_backfill=True)
    with pytest.raises(ValueError, match="mutually exclusive"):
        rehearsal.run_helper(environment(), {}, rollback_backfill=True, interrupt=True)


def test_rollback_injection_occurs_only_after_named_disable_executes(monkeypatch):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from alembic import op
    from scripts import release_companies_traveller_upgrade as helper

    executed = []
    def execute(self, statement, *args, **kwargs):
        executed.append(statement)
    monkeypatch.setattr(Operations, "execute", execute)
    monkeypatch.setattr(sys, "argv", ["synthetic-injection", "{}"])
    statements = ["SET LOCAL lock_timeout = '5s'",
                  "ALTER TABLE public.client_groups DISABLE TRIGGER group_roster_revision"]
    def apply(_contract):
        with Operations.context(MigrationContext.configure(dialect_name="postgresql")):
            for statement in statements:
                op.execute(statement)
        pytest.fail("Injection did not stop after disabling the named trigger")
    monkeypatch.setattr(helper, "apply_upgrade", apply)
    with pytest.raises(SystemExit) as raised:
        exec(rehearsal.BACKFILL_ROLLBACK_RUNNER, {})
    assert raised.value.code == 74
    assert executed == statements


def test_invalid_index_fixture_requires_real_failed_build():
    connection, cursor = Mock(), Mock()
    connection.cursor.return_value.__enter__ = Mock(return_value=cursor)
    connection.cursor.return_value.__exit__ = Mock(return_value=False)
    with pytest.raises(AssertionError, match="unexpectedly succeeded"):
        create_interrupted_source_index(connection)
    assert connection.autocommit is False


@pytest.mark.parametrize("validity", [False, True])
def test_invalid_index_fixture_checks_postgresql_state_after_expected_failure(validity):
    connection, cursor = Mock(), Mock()
    connection.cursor.return_value.__enter__ = Mock(return_value=cursor)
    connection.cursor.return_value.__exit__ = Mock(return_value=False)
    cursor.execute.side_effect = [psycopg2.errors.UniqueViolation("synthetic duplicate"), None]
    cursor.fetchone.return_value = (validity,)
    if validity:
        with pytest.raises(AssertionError, match="expected invalid index"):
            create_interrupted_source_index(connection)
    else:
        create_interrupted_source_index(connection)
    assert connection.autocommit is False
