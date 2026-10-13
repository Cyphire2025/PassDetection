"""Guard the destructive CI scope and exercise forward-resume assertions."""

from types import SimpleNamespace
from unittest.mock import Mock

import psycopg2
import pytest

from scripts import rehearse_companies_traveller_upgrade as rehearsal
from scripts.companies_rehearsal_fixture import create_interrupted_source_index


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
    runner = Mock(side_effect=[{"status": "baseline_captured", "preservation_sha256": baseline}, {"exit_code": 73},
        {"status": "failed"},
        {"started_schema": rehearsal.CHAIN[1], "executed_revisions": list(rehearsal.CHAIN[2:])},
        {"status": "already_at_target", "executed_revisions": []}])
    invalid_index = Mock()
    monkeypatch.setattr(rehearsal, "run_helper", runner)
    monkeypatch.setattr(rehearsal, "_connect", Mock(return_value=connection))
    monkeypatch.setattr(rehearsal, "_revision", Mock(return_value=rehearsal.CHAIN[1]))
    monkeypatch.setattr(rehearsal, "create_interrupted_source_index", invalid_index)
    monkeypatch.setattr(rehearsal, "snapshot", Mock(return_value=before))
    result = rehearsal.exercise_resume(environment(), {}, before)
    assert runner.call_count == 5 and runner.call_args_list[0].kwargs == {"capture_baseline": True}
    assert runner.call_args_list[1].kwargs == {"interrupt": True, "baseline_sha256": baseline}
    assert runner.call_args_list[2].kwargs == {"baseline_sha256": "0" * 64, "expect_rejection": True}
    assert all(call.kwargs["baseline_sha256"] == baseline for call in runner.call_args_list[3:])
    invalid_index.assert_called_once_with(connection)
    assert connection.close.call_count == 2
    assert result["invalid_concurrent_index_repaired"] is True
    assert result["wrong_baseline_rejected_before_ddl"] is True


def test_resume_rejects_historical_mutation_before_continuing(monkeypatch):
    runner = Mock(side_effect=[{"status": "baseline_captured",
        "preservation_sha256": rehearsal.preservation_digest({"rows": "original"})}, {"exit_code": 73}])
    monkeypatch.setattr(rehearsal, "run_helper", runner)
    monkeypatch.setattr(rehearsal, "_connect", Mock(return_value=Mock()))
    monkeypatch.setattr(rehearsal, "_revision", Mock(return_value=rehearsal.CHAIN[1]))
    monkeypatch.setattr(rehearsal, "create_interrupted_source_index", Mock())
    monkeypatch.setattr(rehearsal, "snapshot", Mock(return_value={"rows": "changed"}))
    with pytest.raises(AssertionError, match="changed historical"):
        rehearsal.exercise_resume(environment(), {}, {"rows": "original"})
    assert runner.call_count == 2


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
