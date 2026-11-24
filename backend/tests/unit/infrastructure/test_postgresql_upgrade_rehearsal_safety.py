"""No PostgreSQL operation may receive a silently truncated rehearsal name."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import postgresql_rehearsal_client, postgresql_rehearsal_runner
from tests.unit.infrastructure.test_postgresql_upgrade_rehearsal import _load_script

MAXIMUM_NAME = "passdetection_ci_" + "a" * (63 - len("passdetection_ci_"))
ENVIRONMENT = {
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "synthetic-rehearsal-user",
    "POSTGRES_PASSWORD": "synthetic-only-rehearsal-password",
    "POSTGRES_DB": MAXIMUM_NAME,
}


def test_maximum_postgresql_identifier_length_remains_accepted():
    rehearsal = _load_script()
    assert len(MAXIMUM_NAME.encode("ascii")) == 63
    assert rehearsal.validate_database_name(MAXIMUM_NAME) == MAXIMUM_NAME


@pytest.mark.parametrize("operation", ["validate", "environment", "drop", "create"])
def test_truncated_database_alias_fails_before_any_connection(monkeypatch, operation):
    rehearsal = _load_script()
    connect = Mock(side_effect=AssertionError("must not connect for a truncated database alias"))
    monkeypatch.setattr(postgresql_rehearsal_client, "_connect", connect)
    name = MAXIMUM_NAME + "a"
    assert name != ENVIRONMENT["POSTGRES_DB"]
    assert name[:63] == ENVIRONMENT["POSTGRES_DB"]
    functions = {
        "validate": lambda: rehearsal.validate_database_name(name),
        "environment": lambda: rehearsal.database_environment(ENVIRONMENT, name),
        "drop": lambda: rehearsal._drop_database(ENVIRONMENT, name),
        "create": lambda: rehearsal._create_database(ENVIRONMENT, name),
    }
    with pytest.raises(ValueError, match="63"):
        functions[operation]()
    connect.assert_not_called()


@pytest.mark.parametrize("side", ["source", "restored"])
def test_truncated_alias_of_configured_database_fails_before_cli_or_database_work(
    monkeypatch,
    tmp_path: Path,
    side,
):
    rehearsal = _load_script()
    for key, value in ENVIRONMENT.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv(rehearsal.DESTRUCTIVE_ACKNOWLEDGEMENT, "1")
    run = Mock(side_effect=AssertionError("must not invoke PostgreSQL CLI before admission"))
    replace = Mock(side_effect=AssertionError("must not replace a truncated database alias"))
    monkeypatch.setattr(postgresql_rehearsal_runner, "_run", run)
    monkeypatch.setattr(postgresql_rehearsal_runner, "_replace_database", replace)
    source = MAXIMUM_NAME + "s" if side == "source" else "passdetection_ci_source"
    restored = MAXIMUM_NAME + "r" if side == "restored" else "passdetection_ci_restored"
    with pytest.raises(ValueError, match="63"):
        rehearsal.rehearse(
            backend_root=tmp_path,
            evidence_output=tmp_path / "never-written.json",
            source_database=source,
            restored_database=restored,
        )
    run.assert_not_called()
    replace.assert_not_called()
    assert not (tmp_path / "never-written.json").exists()
