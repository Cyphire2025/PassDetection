"""PostgreSQL synthetic rehearsal runner owner."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from scripts.postgresql_rehearsal_client import (
    _alembic,
    _client_major,
    _connect,
    _drop_database,
    _replace_database,
    _run,
    _sha256,
    _timed_stage,
    database_environment,
    require_destructive_acknowledgement,
    validate_database_name,
)
from scripts.postgresql_rehearsal_contract import EXPECTED_HEAD_REVISION, PREVIOUS_RELEASE_REVISION
from scripts.postgresql_rehearsal_fixture import _seed_previous_release
from scripts.postgresql_rehearsal_snapshot import (
    _assert_snapshot_equal,
    _previous_release_snapshot,
    _revision,
    _scalar,
)
from scripts.postgresql_rehearsal_verification import _verify_upgraded_database


def rehearse(
    *,
    backend_root: Path,
    evidence_output: Path,
    source_database: str,
    restored_database: str,
) -> dict[str, Any]:
    source_database = validate_database_name(source_database)
    restored_database = validate_database_name(restored_database)
    configured_database = os.environ.get("POSTGRES_DB", "")
    if source_database == restored_database:
        raise ValueError("Source and restored rehearsal databases must differ")
    if configured_database in {source_database, restored_database}:
        raise ValueError("Rehearsal databases must differ from POSTGRES_DB")

    base_environment = dict(os.environ)
    require_destructive_acknowledgement(base_environment)
    source_environment = database_environment(base_environment, source_database)
    restored_environment = database_environment(base_environment, restored_database)
    timings: dict[str, float] = {}
    started_at = time.time()

    pg_dump_version = _run(
        ["pg_dump", "--version"],
        cwd=backend_root,
        environment=base_environment,
        capture_output=True,
    ).stdout.strip()
    pg_restore_version = _run(
        ["pg_restore", "--version"],
        cwd=backend_root,
        environment=base_environment,
        capture_output=True,
    ).stdout.strip()

    try:
        _timed_stage(
            timings,
            "create_source_database_seconds",
            lambda: _replace_database(base_environment, source_database),
        )
        _timed_stage(
            timings,
            "migrate_source_to_0085_seconds",
            lambda: _alembic(
                backend_root,
                source_environment,
                "upgrade",
                PREVIOUS_RELEASE_REVISION,
            ),
        )

        source_connection = _connect(base_environment, source_database)
        try:
            if _revision(source_connection) != PREVIOUS_RELEASE_REVISION:
                raise AssertionError("Source database did not stop at the previous release")
            _timed_stage(
                timings,
                "seed_previous_release_seconds",
                lambda: _seed_previous_release(source_connection),
            )
            source_snapshot = _previous_release_snapshot(source_connection)
            server_major = (
                int(_scalar(source_connection, "SELECT current_setting('server_version_num')"))
                // 10000
            )
        finally:
            source_connection.close()

        if _client_major(pg_dump_version) != server_major:
            raise AssertionError(
                f"pg_dump major must match PostgreSQL server major {server_major}: "
                f"{pg_dump_version}"
            )
        if _client_major(pg_restore_version) != server_major:
            raise AssertionError(
                f"pg_restore major must match PostgreSQL server major {server_major}: "
                f"{pg_restore_version}"
            )

        with tempfile.TemporaryDirectory(prefix="passdetection-ci-migration-") as temporary:
            dump_path = Path(temporary) / "previous-release.dump"
            _timed_stage(
                timings,
                "pg_dump_seconds",
                lambda: _run(
                    [
                        "pg_dump",
                        "--format=custom",
                        "--no-owner",
                        "--no-acl",
                        "--file",
                        str(dump_path),
                        source_database,
                    ],
                    cwd=backend_root,
                    environment=source_environment,
                ),
            )
            dump_sha256 = _sha256(dump_path)
            dump_bytes = dump_path.stat().st_size
            if dump_bytes <= 0:
                raise AssertionError("pg_dump produced an empty backup")

            _timed_stage(
                timings,
                "create_restored_database_seconds",
                lambda: _replace_database(base_environment, restored_database),
            )
            _timed_stage(
                timings,
                "pg_restore_seconds",
                lambda: _run(
                    [
                        "pg_restore",
                        "--exit-on-error",
                        "--single-transaction",
                        "--no-owner",
                        "--no-acl",
                        "--dbname",
                        restored_database,
                        str(dump_path),
                    ],
                    cwd=backend_root,
                    environment=restored_environment,
                ),
            )

            restored_connection = _connect(base_environment, restored_database)
            try:
                restored_snapshot = _previous_release_snapshot(restored_connection)
                _assert_snapshot_equal(source_snapshot, restored_snapshot)
            finally:
                restored_connection.close()

        _timed_stage(
            timings,
            "upgrade_restored_to_head_seconds",
            lambda: _alembic(backend_root, restored_environment, "upgrade", "head"),
        )
        current_output = _alembic(
            backend_root,
            restored_environment,
            "current",
            capture_output=True,
        ).stdout.strip()
        check_output = _alembic(
            backend_root,
            restored_environment,
            "check",
            capture_output=True,
        ).stdout.strip()
        _run(
            [sys.executable, "scripts/verify_migration_topology.py"],
            cwd=backend_root,
            environment=restored_environment,
        )

        restored_connection = _connect(base_environment, restored_database)
        try:
            head_verification = _verify_upgraded_database(restored_connection)
        finally:
            restored_connection.close()

        evidence = {
            "contract_version": 1,
            "scope": "synthetic CI PostgreSQL restore and forward-upgrade rehearsal",
            "production_resilience_proof": False,
            "source_revision": PREVIOUS_RELEASE_REVISION,
            "restored_pre_upgrade_revision": restored_snapshot["revision"],
            "reviewed_head_revision": EXPECTED_HEAD_REVISION,
            "alembic_current": current_output,
            "alembic_check": check_output,
            "postgresql_server_major": server_major,
            "pg_dump_version": pg_dump_version,
            "pg_restore_version": pg_restore_version,
            "dump": {"sha256": dump_sha256, "bytes": dump_bytes, "retained": False},
            "source_0085_snapshot": source_snapshot,
            "restored_0085_snapshot": restored_snapshot,
            "head_verification": head_verification,
            "timings": timings,
            "elapsed_seconds": round(time.time() - started_at, 3),
        }
        evidence_output.parent.mkdir(parents=True, exist_ok=True)
        evidence_output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Migration rehearsal passed; evidence written to {evidence_output}")
        return evidence
    finally:
        _drop_database(base_environment, restored_database)
        _drop_database(base_environment, source_database)


# Preserve canonical public import/pickle identities through the CLI facade.
for _export in (rehearse,):
    _export.__module__ = "scripts.rehearse_postgresql_upgrade"
del _export
