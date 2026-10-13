"""Distinct role custody and cleanup in the disposable populated rehearsal."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from scripts import companies_rehearsal_fixture as fixture
from scripts import rehearse_companies_traveller_upgrade as rehearsal


def admin():
    return {"POSTGRES_USER": "bootstrap", "POSTGRES_PASSWORD": "synthetic-admin",
        "POSTGRES_HOST": "localhost", "POSTGRES_DB": "test_db", "PGUSER": "bootstrap",
        "PGPASSWORD": "synthetic-admin"}


@pytest.mark.parametrize("failure", [False, True])
def test_owner_is_restricted_distinct_and_removed_after_caller_cleanup(monkeypatch, failure):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    events = []
    cursor.execute.side_effect = lambda statement, *args: events.append(str(statement))
    connect = Mock(return_value=connection)
    monkeypatch.setattr(fixture, "_connect", connect)
    original = admin()
    try:
        with fixture.migration_owner(original) as owner:
            assert owner["POSTGRES_USER"] != original["POSTGRES_USER"]
            assert owner["POSTGRES_PASSWORD"] != original["POSTGRES_PASSWORD"]
            assert owner["PGUSER"] == owner["POSTGRES_USER"]
            assert owner["PGPASSWORD"] == owner["POSTGRES_PASSWORD"]
            assert owner["POSTGRES_HOST"] == original["POSTGRES_HOST"]
            events.append("databases removed by caller")
            if failure:
                raise RuntimeError("synthetic failure")
    except RuntimeError:
        assert failure
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE" in events[0]
    assert "NOINHERIT NOREPLICATION NOBYPASSRLS" in events[0]
    assert "CREATE ROLE passdetection_ci_companies_runtime NOLOGIN" in events[1]
    assert events[-2] == "databases removed by caller"
    assert "DROP ROLE" in events[-1]
    assert original == admin()
    assert all(call.args == (original, "postgres") for call in connect.call_args_list)


def test_role_creation_failure_never_yields_credentials_or_drops_another_role(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = RuntimeError("role create rejected")
    monkeypatch.setattr(fixture, "_connect", Mock(return_value=connection))
    with pytest.raises(RuntimeError, match="role create rejected"), fixture.migration_owner(admin()):
        pytest.fail("Failed role creation must not yield")
    assert cursor.execute.call_count == 1
    connection.commit.assert_not_called()
    connection.close.assert_called_once()


def test_database_creation_uses_admin_but_returns_only_owner_credentials(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    replace = Mock()
    monkeypatch.setattr(fixture, "_replace_database", replace)
    monkeypatch.setattr(fixture, "_connect", Mock(return_value=connection))
    owner = {**admin(), "POSTGRES_USER": "synthetic_owner", "POSTGRES_PASSWORD": "synthetic-owner"}
    name = "passdetection_ci_companies_source"
    environment = fixture.replace_owned_database(admin(), owner, name)
    replace.assert_called_once_with(admin(), name)
    statement = str(cursor.execute.call_args.args[0])
    assert "ALTER DATABASE" in statement and "synthetic_owner" in statement and name in statement
    assert environment["POSTGRES_USER"] == environment["PGUSER"] == "synthetic_owner"
    assert environment["POSTGRES_PASSWORD"] == environment["PGPASSWORD"] == "synthetic-owner"
    assert environment["POSTGRES_DB"] == environment["PGDATABASE"] == name


def test_every_migration_restore_and_resume_runs_as_owner_not_bootstrap(monkeypatch, tmp_path):
    owner = {**admin(), "POSTGRES_USER": "synthetic_owner", "POSTGRES_PASSWORD": "synthetic-owner"}
    before = {"catalog": {}, "rows": {"whatsapp_broadcast_rejected_contacts": {"count": 699}}}
    phases = []
    def replace(bootstrap, identity, name):
        assert bootstrap == admin() and identity == owner
        return fixture.database_environment(identity, name)
    def run(arguments, *, cwd, environment, capture_output=False):
        if "--version" in arguments:
            return SimpleNamespace(stdout=arguments[0] + " (PostgreSQL) 16.15")
        phases.append((arguments[0], environment["POSTGRES_USER"]))
        if "--file" in arguments:
            Path(arguments[arguments.index("--file") + 1]).write_bytes(b"synthetic populated backup")
        return SimpleNamespace(stdout="")
    alembic = Mock(side_effect=lambda _root, env, *args: phases.append(("alembic", env["POSTGRES_USER"])))
    connect = Mock(return_value=MagicMock())
    bootstrap_rejection = Mock(return_value={"exit_code": 75, "reason": "existing_migration_identity_required"})
    resume = Mock(return_value={"company_backfill_rollback_verified": True})
    monkeypatch.setattr(rehearsal, "replace_owned_database", replace)
    monkeypatch.setattr(rehearsal, "_connect", connect)
    monkeypatch.setattr(rehearsal, "_alembic", alembic)
    monkeypatch.setattr(rehearsal, "_seed_previous_release", Mock())
    monkeypatch.setattr(rehearsal, "seed_company_and_roster", Mock())
    monkeypatch.setattr(rehearsal, "_scalar", Mock(return_value=160015))
    monkeypatch.setattr(rehearsal, "_revision", Mock(return_value=rehearsal.SOURCE))
    monkeypatch.setattr(rehearsal, "_run", run)
    monkeypatch.setattr(rehearsal, "snapshot", Mock(return_value=before))
    monkeypatch.setattr(rehearsal, "run_helper", bootstrap_rejection)
    monkeypatch.setattr(rehearsal, "exercise_resume", resume)
    cleanup = Mock()
    monkeypatch.setattr(rehearsal, "_drop_database", cleanup)
    result = rehearsal.rehearse_owned(admin(), owner, tmp_path / "receipt.json")
    assert len(phases) == 5 and all(role == "synthetic_owner" for _, role in phases)
    assert all(call.args[0] == owner for call in connect.call_args_list)
    assert resume.call_args.args[0]["POSTGRES_USER"] == "synthetic_owner"
    assert bootstrap_rejection.call_args.args[0]["POSTGRES_USER"] == "bootstrap"
    assert bootstrap_rejection.call_args.kwargs == {"reject_bootstrap": True}
    assert result["split_migration_role_verified"] is True
    assert cleanup.call_args_list[0].args == (admin(), rehearsal.RESTORED_DATABASE)
    assert cleanup.call_args_list[1].args == (admin(), rehearsal.SOURCE_DATABASE)
