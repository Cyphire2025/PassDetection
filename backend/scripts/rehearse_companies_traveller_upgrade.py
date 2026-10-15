"""Synthetic populated 0135 restore, transactional failures and forward resume.

Never targets POSTGRES_DB or production. The explicit destructive acknowledgement,
loopback host and exact synthetic database names are mandatory. All migration
work runs through the same source-bound helper used by the retained Full release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.companies_client_data_fixture import (  # noqa: E402
    seed_retained_history,
    verify_detached_manager_constraints,
)
from scripts.companies_rehearsal_fixture import (  # noqa: E402
    migration_owner,
    replace_owned_database,
    seed_company_and_roster,
)
from scripts.companies_restore_comparison import restored_baseline  # noqa: E402
from scripts.companies_traveller_release_schema import preservation_snapshot  # noqa: E402
from scripts.companies_traveller_reuse_release import (  # noqa: E402
    CHAIN,
    POLICY,
    SOURCE,
    TARGET,
    migration_entries,
)
from scripts.historical_migration_rehearsal import historical_tree  # noqa: E402
from scripts.rehearse_postgresql_upgrade import (  # noqa: E402
    PREVIOUS_RELEASE_REVISION,
    _alembic,
    _client_major,
    _connect,
    _drop_database,
    _revision,
    _run,
    _scalar,
    _seed_previous_release,
    _sha256,
    database_environment,
    require_destructive_acknowledgement,
)
from scripts.release_companies_traveller_upgrade import preservation_digest  # noqa: E402
from scripts.release_travel_tracker_upgrade import _dml_grants  # noqa: E402

SOURCE_DATABASE = "passdetection_ci_companies_source"
RESTORED_DATABASE = "passdetection_ci_companies_restored"
INTERRUPTED_EXIT = 73
DRAFT_ROLLBACK_EXIT = 74
BOOTSTRAP_REJECTION_EXIT = 75
DIRECTORY_ROLLBACK_EXIT = 76
LOOKUP_ROLLBACK_EXIT = 77
BOOTSTRAP_REJECTION_RUNNER = """
import json, sys
from scripts.release_companies_traveller_upgrade import apply_upgrade
try:
    apply_upgrade(json.loads(sys.argv[1]), capture_baseline=True)
except ValueError as failure:
    if str(failure) == 'existing_migration_identity_required':
        raise SystemExit(75)
    raise
raise SystemExit('Expected bootstrap migration identity rejection did not occur')
"""
DRAFT_ROLLBACK_RUNNER = """
import json, sys
from alembic.operations import Operations
from scripts.release_companies_traveller_upgrade import apply_upgrade
original = Operations.execute
class InjectedDraftFailure(Exception):
    pass

def fail_after_create(self, statement, *args, **kwargs):
    result = original(self, statement, *args, **kwargs)
    if str(statement).startswith('CREATE TABLE traveller_returning_drafts '):
        raise InjectedDraftFailure('synthetic failure after draft table create')
    return result
Operations.execute = fail_after_create
try:
    apply_upgrade(json.loads(sys.argv[1]))
except InjectedDraftFailure:
    raise SystemExit(74)
raise SystemExit('Expected draft DDL rollback injection did not occur')
"""
DIRECTORY_ROLLBACK_RUNNER = """
import json, sys
from alembic.operations import Operations
from scripts.release_companies_traveller_upgrade import apply_upgrade
original = Operations.create_table
class InjectedDirectoryFailure(Exception):
    pass

def fail_after_create(self, table, *args, **kwargs):
    result = original(self, table, *args, **kwargs)
    if table == 'company_directory_states':
        raise InjectedDirectoryFailure('synthetic failure after directory table create')
    return result
Operations.create_table = fail_after_create
try:
    apply_upgrade(json.loads(sys.argv[1]))
except InjectedDirectoryFailure:
    raise SystemExit(76)
raise SystemExit('Expected directory DDL rollback injection did not occur')
"""
LOOKUP_ROLLBACK_RUNNER = """
import json, sys
from alembic.operations import Operations
from scripts.release_companies_traveller_upgrade import apply_upgrade
original = Operations.create_check_constraint
class InjectedLookupFailure(Exception):
    pass
def fail_after_constraint(self, name, table, *args, **kwargs):
    result = original(self, name, table, *args, **kwargs)
    if name == 'ck_traveller_claim_actor' and table == 'traveller_claims':
        raise InjectedLookupFailure('synthetic failure after actor check change')
    return result
Operations.create_check_constraint = fail_after_constraint
try:
    apply_upgrade(json.loads(sys.argv[1]))
except InjectedLookupFailure:
    raise SystemExit(77)
raise SystemExit('Expected lookup DDL rollback injection did not occur')
"""
INTERRUPTION_RUNNER = """
import json, sys
from alembic import command
from scripts.release_companies_traveller_upgrade import apply_upgrade
original = command.upgrade
def interrupt(config, revision):
    if revision == '0137_company_directory':
        raise InterruptedError('synthetic checkpoint interruption')
    return original(config, revision)
command.upgrade = interrupt
try:
    apply_upgrade(json.loads(sys.argv[1]))
except InterruptedError:
    raise SystemExit(73)
raise SystemExit('Expected checkpoint interruption did not occur')
"""


def validate_environment(environment: Mapping[str, str]) -> None:
    require_destructive_acknowledgement(environment)
    if environment.get("POSTGRES_HOST") not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Only a loopback disposable PostgreSQL service is permitted")
    if environment.get("POSTGRES_DB") in {SOURCE_DATABASE, RESTORED_DATABASE}:
        raise ValueError("Rehearsal databases must differ from POSTGRES_DB")


def snapshot(environment: Mapping[str, str], schema: str) -> dict[str, Any]:
    url = URL.create("postgresql+psycopg2", username=environment["POSTGRES_USER"],
        password=environment["POSTGRES_PASSWORD"], host=environment["POSTGRES_HOST"],
        port=int(environment.get("POSTGRES_PORT", "5432")), database=environment["POSTGRES_DB"])
    engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 10,
        "options": "-c statement_timeout=120000 -c work_mem=16MB"})
    try:
        with engine.connect() as connection:
            retained = preservation_snapshot(connection, ROOT, schema)
            runtime_grants = sorted(_dml_grants(connection, "passport_submissions"))
            if len(runtime_grants) < 4:
                raise AssertionError("Synthetic runtime DML grants must be nonempty")
            return {**retained, "runtime_grants": runtime_grants}
    finally:
        engine.dispose()


def run_helper(environment: Mapping[str, str], contract: dict[str, Any], *, interrupt: bool = False,
               capture_baseline: bool = False, baseline_sha256: str | None = None,
               expect_rejection: bool = False, rollback_draft: bool = False,
               reject_bootstrap: bool = False, rollback_directory: bool = False,
               rollback_lookup: bool = False) -> dict[str, Any]:
    if sum((interrupt, capture_baseline, expect_rejection, rollback_draft, reject_bootstrap, rollback_directory, rollback_lookup)) > 1:
        raise ValueError("Rehearsal helper modes are mutually exclusive")
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":"))
    # Synthetic CI proof marker; host release authorization is qualified by its
    # separate signed-image/fence tests. It is not represented as production proof.
    child_environment = {**environment, "MCP_RELEASE_PROOF_SHA256": hashlib.sha256(encoded.encode()).hexdigest()}
    if baseline_sha256 is not None:
        child_environment["MCP_RELEASE_BASELINE_SHA256"] = baseline_sha256
    runner = DRAFT_ROLLBACK_RUNNER if rollback_draft else INTERRUPTION_RUNNER
    if rollback_directory:
        runner = DIRECTORY_ROLLBACK_RUNNER
    if rollback_lookup:
        runner = LOOKUP_ROLLBACK_RUNNER
    if reject_bootstrap:
        runner = BOOTSTRAP_REJECTION_RUNNER
    if not (interrupt or rollback_draft or reject_bootstrap or rollback_directory or rollback_lookup):
        runner = "import sys\nfrom scripts.release_companies_traveller_upgrade import main\nsys.argv = ['release_companies_traveller_upgrade.py', '--contract-json', *sys.argv[1:]]\nraise SystemExit(main())\n"
    # Keep the production helper's exact-head check. A current checkout also
    # contains later migrations, so this historical rehearsal gives only its
    # subprocess a temporary copy of the original image's migration ancestry.
    prefix = "import sys\nfrom pathlib import Path\nfrom scripts import release_companies_traveller_upgrade as historical_helper\nhistorical_helper.ROOT = Path(sys.argv.pop(1))\n"
    with historical_tree(ROOT, TARGET) as migration_root:
        arguments = [sys.executable, "-c", prefix + runner, str(migration_root), encoded]
        if capture_baseline:
            arguments.append("--capture-baseline")
        result = subprocess.run(arguments, cwd=ROOT, env=child_environment, capture_output=True,
            text=True, timeout=600, check=False, shell=False)
    expected = DRAFT_ROLLBACK_EXIT if rollback_draft else (INTERRUPTED_EXIT if interrupt else (2 if expect_rejection else 0))
    if rollback_directory:
        expected = DIRECTORY_ROLLBACK_EXIT
    if rollback_lookup:
        expected = LOOKUP_ROLLBACK_EXIT
    if reject_bootstrap:
        expected = BOOTSTRAP_REJECTION_EXIT
    if result.returncode != expected:
        # Driver failures may contain DSNs. Preserve a safe failure code only.
        raise RuntimeError(f"Upgrade helper failed: expected exit {expected}, observed {result.returncode}")
    if interrupt:
        return {"exit_code": result.returncode, "interrupted_before": CHAIN[1]}
    if rollback_draft:
        return {"exit_code": result.returncode, "rolled_back_revision": CHAIN[0]}
    if rollback_directory:
        return {"exit_code": result.returncode, "rolled_back_revision": CHAIN[1]}
    if rollback_lookup:
        return {"exit_code": result.returncode, "rolled_back_revision": CHAIN[2]}
    if reject_bootstrap:
        return {"exit_code": result.returncode, "reason": "existing_migration_identity_required"}
    value: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    if expect_rejection:
        if value != {"status": "failed", "reason": "companies_traveller_upgrade_failed", "automatic_downgrade": False}:
            raise AssertionError("Unexpected negative-control helper receipt")
        return value
    if value.get("target_schema") != TARGET or value.get("automatic_downgrade") is not False:
        raise AssertionError("Unexpected upgrade-helper receipt")
    return value


def exercise_resume(environment: Mapping[str, str], contract: dict[str, Any], before: dict[str, Any]) -> dict[str, Any]:
    baseline = preservation_digest({key: value for key, value in before.items() if key != "runtime_grants"})
    rollback = run_helper(environment, contract, rollback_draft=True, baseline_sha256=baseline)
    connection = _connect(environment, RESTORED_DATABASE)
    try:
        if _revision(connection) != SOURCE:
            raise AssertionError("Draft DDL failure did not roll back the complete 0136 revision")
    finally:
        connection.close()
    if snapshot(environment, SOURCE) != before:
        raise AssertionError("Draft rollback changed historical data, ACL or retained schema")
    captured = run_helper(environment, contract, capture_baseline=True)
    if captured.get("status") != "baseline_captured" or captured.get("preservation_sha256") != baseline:
        raise AssertionError("Original helper baseline does not match the restored backup")
    interruption = run_helper(environment, contract, interrupt=True, baseline_sha256=baseline)
    connection = _connect(environment, RESTORED_DATABASE)
    try:
        if _revision(connection) != CHAIN[0]:
            raise AssertionError("Interruption did not preserve committed 0136 checkpoint")
    finally:
        connection.close()
    if snapshot(environment, CHAIN[0]) != before:
        raise AssertionError("Partial upgrade changed historical data, ACL or retained schema")
    directory_rollback = run_helper(environment, contract, rollback_directory=True, baseline_sha256=baseline)
    connection = _connect(environment, RESTORED_DATABASE)
    try:
        if _revision(connection) != CHAIN[0] or snapshot(environment, CHAIN[0]) != before:
            raise AssertionError("Directory rollback changed historical data, ACL or retained schema")
    finally:
        connection.close()
    run_helper(environment, contract, baseline_sha256="0" * 64, expect_rejection=True)
    connection = _connect(environment, RESTORED_DATABASE)
    try:
        if _revision(connection) != CHAIN[0]:
            raise AssertionError("Wrong-baseline rejection advanced the partial schema")
    finally:
        connection.close()
    lookup_rollback = run_helper(environment, contract, rollback_lookup=True, baseline_sha256=baseline)
    connection = _connect(environment, RESTORED_DATABASE)
    try:
        if _revision(connection) != CHAIN[1] or snapshot(environment, CHAIN[1]) != before:
            raise AssertionError("Lookup rollback changed historical data, actor evidence or retained schema")
    finally:
        connection.close()
    resumed = run_helper(environment, contract, baseline_sha256=baseline)
    if resumed.get("started_schema") != CHAIN[1] or resumed.get("executed_revisions") != list(CHAIN[2:]):
        raise AssertionError("Forward resume did not start at the committed checkpoint")
    if snapshot(environment, TARGET) != before:
        raise AssertionError("Forward resume changed historical data, ACL or retained schema")
    connection = _connect(environment, RESTORED_DATABASE)
    try:
        verify_detached_manager_constraints(connection)
    finally:
        connection.close()
    if snapshot(environment, TARGET) != before:
        raise AssertionError("Manager constraint probes changed historical records")
    noop = run_helper(environment, contract, baseline_sha256=baseline)
    if noop.get("status") != "already_at_target" or noop.get("executed_revisions") != []:
        raise AssertionError("Completed upgrade was not idempotent")
    return {"original_preservation_baseline": captured, "interruption": interruption,
        "draft_ddl_rollback": rollback, "draft_ddl_rollback_verified": True,
        "directory_ddl_rollback": directory_rollback, "directory_ddl_rollback_verified": True,
        "lookup_ddl_rollback": lookup_rollback, "lookup_ddl_rollback_verified": True,
        "manager_constraints_verified": True, "wrong_baseline_rejected_before_ddl": True,
        "resume": resumed, "noop": noop}


def rehearse(evidence_output: Path) -> dict[str, Any]:
    environment = dict(os.environ)
    validate_environment(environment)
    with migration_owner(environment) as owner:
        return rehearse_owned(environment, owner, evidence_output)


def rehearse_owned(environment: Mapping[str, str], owner: Mapping[str, str], evidence_output: Path) -> dict[str, Any]:
    """Exercise the real owner identity, separately from bootstrap and runtime roles."""
    contract = {**POLICY, "migrations": migration_entries(ROOT)}
    started = time.monotonic()
    try:
        source = replace_owned_database(environment, owner, SOURCE_DATABASE)
        _alembic(ROOT, source, "upgrade", PREVIOUS_RELEASE_REVISION)
        connection = _connect(owner, SOURCE_DATABASE)
        try:
            _seed_previous_release(connection)
        finally:
            connection.close()
        _alembic(ROOT, source, "upgrade", "0129_travel_tracker")
        connection = _connect(owner, SOURCE_DATABASE)
        try:
            seed_company_and_roster(connection)
        finally:
            connection.close()
        _alembic(ROOT, source, "upgrade", SOURCE)
        connection = _connect(owner, SOURCE_DATABASE)
        try:
            seed_retained_history(connection)
            server_major = int(_scalar(connection, "SHOW server_version_num")) // 10000
        finally:
            connection.close()
        versions = {name: _run([name, "--version"], cwd=ROOT, environment=environment,
            capture_output=True).stdout.strip() for name in ("pg_dump", "pg_restore")}
        if any(_client_major(version) != server_major for version in versions.values()):
            raise AssertionError("PostgreSQL backup clients must match the server major")
        before = snapshot(source, SOURCE)
        rejected = run_helper(database_environment(environment, SOURCE_DATABASE), contract, reject_bootstrap=True)
        connection = _connect(owner, SOURCE_DATABASE)
        try:
            if _revision(connection) != SOURCE or snapshot(source, SOURCE) != before:
                raise AssertionError("Rejected bootstrap identity changed the original database")
        finally:
            connection.close()
        if before["rows"]["whatsapp_broadcast_rejected_contacts"]["count"] != 699:
            raise AssertionError("Synthetic durable-roster fixture is incomplete")
        with tempfile.TemporaryDirectory(prefix="passdetection-ci-companies-") as temporary:
            dump = Path(temporary) / "populated-0135.dump"
            # Preserve ACLs in the same disposable cluster so runtime grants are
            # a real verification obligation, rather than an empty comparison.
            _run(["pg_dump", "--format=custom", "--no-owner", "--file", str(dump), SOURCE_DATABASE],
                cwd=ROOT, environment=source)
            if dump.stat().st_size == 0:
                raise AssertionError("Empty PostgreSQL backup")
            dump_receipt = {"sha256": _sha256(dump), "bytes": dump.stat().st_size}
            restored = replace_owned_database(environment, owner, RESTORED_DATABASE)
            _run(["pg_restore", "--exit-on-error", "--single-transaction", "--no-owner",
                "--dbname", RESTORED_DATABASE, str(dump)], cwd=ROOT, environment=restored)
            before = restored_baseline(before, snapshot(restored, SOURCE))
        result = exercise_resume(restored, contract, before)
        current_head = verify_current_head_mapping(restored)
        evidence = {"version": 1, "scope": "synthetic populated PostgreSQL 0135-to-0138 targeted rehearsal",
            "production_release_authorization": False, "source_revision": SOURCE, "target_revision": TARGET,
            "dump": dump_receipt, "backup_clients": versions, "server_major": server_major,
            "historical_row_counts": {name: value["count"] for name, value in before["rows"].items()},
            "preserved_historical_rows_catalog_acl": True, "new_tables_empty_before_activation": True,
            "runtime_grants_nonempty": True, **result, "current_head_orm_check": current_head,
            "elapsed_seconds": round(time.monotonic() - started, 3)}
        evidence.update(split_migration_role_verified=True, bootstrap_identity_rejection=rejected)
        evidence_output.parent.mkdir(parents=True, exist_ok=True)
        evidence_output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Companies migration rehearsal passed: {evidence_output}")
        return evidence
    finally:
        _drop_database(environment, RESTORED_DATABASE)
        _drop_database(environment, SOURCE_DATABASE)


def verify_current_head_mapping(environment: Mapping[str, str]) -> dict[str, Any]:
    """Check current ORM separately, after the historical preservation proof."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise ValueError("single_current_migration_head_required")
    _alembic(ROOT, environment, "upgrade", heads[0])
    _alembic(ROOT, environment, "check")
    return {"source_after_historical_proof": TARGET, "checked_revision": heads[0],
        "orm_consistent": True, "separate_from_historical_preservation_proof": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-output", type=Path, default=Path("companies-migration-rehearsal-evidence.json"))
    rehearse(parser.parse_args().evidence_output.resolve())
