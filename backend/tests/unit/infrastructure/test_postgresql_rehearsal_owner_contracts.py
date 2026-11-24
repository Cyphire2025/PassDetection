"""Imported operator contracts and constraint controls survive owner moves."""

from __future__ import annotations

import inspect
import pickle
import subprocess
import sys
from types import SimpleNamespace
from typing import get_type_hints

import psycopg2
import pytest

from scripts import postgresql_rehearsal_client as client
from scripts import postgresql_rehearsal_contract as contract
from scripts import postgresql_rehearsal_fixture as fixture
from scripts import postgresql_rehearsal_runner as runner
from scripts import postgresql_rehearsal_snapshot as snapshot
from scripts import postgresql_rehearsal_verification as verification
from scripts import rehearse_postgresql_upgrade as facade


def test_canonical_public_function_aliases_hints_and_pickle_stay_compatible():
    for owner in (client, fixture, runner, snapshot, verification):
        for name, function in vars(owner).items():
            if inspect.isfunction(function) and function.__module__ == facade.__name__:
                assert getattr(facade, name) is function
                assert pickle.loads(pickle.dumps(function)) is function
                assert get_type_hints(function)
    assert facade.IDS is contract.IDS
    assert snapshot.IDS is fixture.IDS is verification.IDS is contract.IDS


def test_direct_cli_help_does_not_require_or_start_a_database():
    result = subprocess.run(
        [sys.executable, facade.__file__, "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    for option in ("--source-database", "--restored-database", "--evidence-output"):
        assert option in result.stdout


class ConstraintFailure(psycopg2.Error):
    @property
    def diag(self):
        return SimpleNamespace(constraint_name="synthetic_tenant_boundary")

    @property
    def pgcode(self):
        return "23514"


@pytest.mark.parametrize("mode", ["expected", "accepted", "wrong-constraint", "wrong-state"])
def test_constraint_probe_requires_actual_rejection_and_restores_its_savepoint(mode):
    calls = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, parameters=None):
            calls.append((statement, parameters))
            if statement == "synthetic unsafe insert" and mode != "accepted":
                raise ConstraintFailure("synthetic test rejection")

    connection = SimpleNamespace(cursor=Cursor)
    constraint = "other_constraint" if mode == "wrong-constraint" else "synthetic_tenant_boundary"
    state = "23503" if mode == "wrong-state" else "23514"

    def probe():
        return facade._assert_constraint_rejected(
            connection,
            statement="synthetic unsafe insert",
            parameters=("synthetic-id",),
            expected_constraint=constraint,
            expected_sqlstate=state,
        )

    if mode == "expected":
        assert probe() == "synthetic_tenant_boundary"
    else:
        with pytest.raises(AssertionError):
            probe()
    assert calls[-2:] == [
        ("ROLLBACK TO SAVEPOINT expected_rehearsal_failure", None),
        ("RELEASE SAVEPOINT expected_rehearsal_failure", None),
    ]
    assert calls[1] == ("synthetic unsafe insert", ("synthetic-id",))
