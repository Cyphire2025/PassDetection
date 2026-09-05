"""Rehearse a populated PostgreSQL backup, restore, and Alembic upgrade.

This script is intentionally destructive only to two explicitly named,
prefix-validated CI databases. It never targets the configured application
database and it seeds synthetic records only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

PREVIOUS_RELEASE_REVISION = "0085_platform_retention_controls"
EXPECTED_HEAD_REVISION = "0090_upload_configuration"
SAFE_DATABASE_NAME = re.compile(r"^passdetection_ci_[a-z0-9_]+$")
PROTECTED_DATABASE_NAMES = frozenset({"postgres", "template0", "template1"})
DESTRUCTIVE_ACKNOWLEDGEMENT = "MIGRATION_REHEARSAL_ALLOW_EPHEMERAL_DATABASE_DELETION"

IDS = {
    "agency_a": "10000000-0000-0000-0000-000000000001",
    "agency_b": "10000000-0000-0000-0000-000000000002",
    "admin_a": "20000000-0000-0000-0000-000000000001",
    "coordinator_a": "20000000-0000-0000-0000-000000000002",
    "coordinator_b": "20000000-0000-0000-0000-000000000003",
    "group_a": "30000000-0000-0000-0000-000000000001",
    "group_b": "30000000-0000-0000-0000-000000000002",
    "passenger_a": "40000000-0000-0000-0000-000000000001",
    "session_a": "50000000-0000-0000-0000-000000000001",
    "attendance_a": "60000000-0000-0000-0000-000000000001",
    "hotel_a": "70000000-0000-0000-0000-000000000001",
    "gc_access_a": "80000000-0000-0000-0000-000000000001",
    "gc_access_b": "80000000-0000-0000-0000-000000000002",
    "closeout_a": "90000000-0000-0000-0000-000000000001",
    "audit_a": "a0000000-0000-0000-0000-000000000001",
    "identity_token_a": "b0000000-0000-0000-0000-000000000001",
    "gallery_a": "c0000000-0000-0000-0000-000000000001",
    "invalid_closeout": "d0000000-0000-0000-0000-000000000001",
    "invalid_gallery": "d0000000-0000-0000-0000-000000000002",
}

PRESERVED_TABLES = (
    "agencies",
    "users",
    "user_security_states",
    "client_groups",
    "passport_submissions",
    "attendance_sessions",
    "attendance_records",
    "attendance_closeout_checkpoints",
    "rooming_hotels",
    "gc_group_access",
    "audit_logs",
    "identity_action_tokens",
)


def validate_database_name(name: str) -> str:
    """Return a safe ephemeral database name or fail closed."""
    if name in PROTECTED_DATABASE_NAMES or not SAFE_DATABASE_NAME.fullmatch(name):
        raise ValueError(
            "Rehearsal database names must match passdetection_ci_[a-z0-9_]+ "
            "and may not name a PostgreSQL system database"
        )
    return name


def database_environment(base: Mapping[str, str], database_name: str) -> dict[str, str]:
    """Build an Alembic/client environment without mutating the process environment."""
    environment = dict(base)
    environment["POSTGRES_DB"] = validate_database_name(database_name)
    environment["PGDATABASE"] = database_name
    environment["PGHOST"] = environment["POSTGRES_HOST"]
    environment["PGPORT"] = environment.get("POSTGRES_PORT", "5432")
    environment["PGUSER"] = environment["POSTGRES_USER"]
    environment["PGPASSWORD"] = environment["POSTGRES_PASSWORD"]
    return environment


def require_destructive_acknowledgement(environment: Mapping[str, str]) -> None:
    """Require an explicit acknowledgement before creating/dropping databases."""
    if environment.get(DESTRUCTIVE_ACKNOWLEDGEMENT) != "1":
        raise RuntimeError(
            f"Set {DESTRUCTIVE_ACKNOWLEDGEMENT}=1 only for isolated rehearsal databases"
        )


def _run(
    arguments: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(arguments), flush=True)
    return subprocess.run(
        list(arguments),
        cwd=cwd,
        env=dict(environment),
        check=True,
        text=True,
        capture_output=capture_output,
        shell=False,
    )


def _connect(environment: Mapping[str, str], database_name: str) -> Connection:
    return psycopg2.connect(
        host=environment["POSTGRES_HOST"],
        port=int(environment.get("POSTGRES_PORT", "5432")),
        user=environment["POSTGRES_USER"],
        password=environment["POSTGRES_PASSWORD"],
        dbname=database_name,
        connect_timeout=10,
        application_name="passdetection-migration-rehearsal",
    )


def _drop_database(environment: Mapping[str, str], database_name: str) -> None:
    database_name = validate_database_name(database_name)
    connection = _connect(environment, "postgres")
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )
    finally:
        connection.close()


def _create_database(environment: Mapping[str, str], database_name: str) -> None:
    database_name = validate_database_name(database_name)
    connection = _connect(environment, "postgres")
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    finally:
        connection.close()


def _replace_database(environment: Mapping[str, str], database_name: str) -> None:
    _drop_database(environment, database_name)
    _create_database(environment, database_name)


def _alembic(
    backend_root: Path,
    environment: Mapping[str, str],
    *arguments: str,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return _run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=backend_root,
        environment=environment,
        capture_output=capture_output,
    )


def _revision(connection: Connection) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        rows = cursor.fetchall()
    if len(rows) != 1:
        raise AssertionError(f"Expected one Alembic head row, found {rows!r}")
    return str(rows[0][0])


def _seed_previous_release(connection: Connection) -> None:
    """Populate 0085 with synthetic cross-domain records and legacy backfill inputs."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO agencies (id, name, email, created_at, updated_at)
            VALUES
                (%(agency_a)s, 'CI Rehearsal Agency A', 'agency-a@example.invalid', now(), now()),
                (%(agency_b)s, 'CI Rehearsal Agency B', 'agency-b@example.invalid', now(), now());

            INSERT INTO users (
                id, email, hashed_password, full_name, role, agency_id, created_at, updated_at
            )
            VALUES
                (%(admin_a)s, 'admin-a@example.invalid', 'synthetic-not-a-password-hash',
                 'CI Admin A', 'agency_admin', %(agency_a)s, now(), now()),
                (%(coordinator_a)s, 'coordinator-a@example.invalid',
                 'synthetic-not-a-password-hash', 'CI Coordinator A',
                 'agency_coordinator', %(agency_a)s, now(), now()),
                (%(coordinator_b)s, 'coordinator-b@example.invalid',
                 'synthetic-not-a-password-hash', 'CI Coordinator B',
                 'agency_coordinator', %(agency_b)s, now(), now());

            INSERT INTO user_security_states (
                user_id, credential_state, session_version, password_changed_at,
                mfa_required, created_at, updated_at
            )
            VALUES
                (%(admin_a)s, 'active', 2, now(), true, now(), now()),
                (%(coordinator_a)s, 'active', 1, now(), false, now(), now()),
                (%(coordinator_b)s, 'active', 1, now(), false, now(), now());

            INSERT INTO platform_settings (key, value, updated_at)
            VALUES (
                'global',
                '{"passport_data_retention_days": 730, "synthetic_rehearsal": true}'::jsonb,
                now()
            );

            INSERT INTO client_groups (
                id, name, token, agency_id, status, created_by_user_id, created_at,
                closed_at, departure_cities, passport_purge_at,
                passport_retention_days_applied
            )
            VALUES
                (%(group_a)s, 'CI Closed Group A', 'ci-rehearsal-group-a', %(agency_a)s,
                 'closed', %(admin_a)s, now() - interval '40 days', now() - interval '10 days',
                 '["Delhi", "Mumbai"]'::jsonb, now() + interval '720 days', 730),
                (%(group_b)s, 'CI Active Group B', 'ci-rehearsal-group-b', %(agency_b)s,
                 'active', %(coordinator_b)s, now() - interval '5 days', NULL,
                 '[]'::jsonb, NULL, NULL);

            INSERT INTO passport_submissions (
                id, group_id, agency_id, client_name, client_email, image_s3_key,
                status, confirmed_fields, created_at, updated_at, confirmed_at
            )
            VALUES (
                %(passenger_a)s, %(group_a)s, %(agency_a)s, 'Synthetic Passenger',
                'passenger@example.invalid', 'ci-only/passports/synthetic.jpg', 'confirmed',
                '{"passport_number": "CI0000001", "synthetic": true}'::jsonb,
                now() - interval '9 days', now() - interval '8 days', now() - interval '8 days'
            );

            INSERT INTO attendance_sessions (
                id, agency_id, group_id, name, normalized_name, canonical_session_id,
                status, created_by_user_id, created_at, updated_at, started_at
            )
            VALUES (
                %(session_a)s, %(agency_a)s, %(group_a)s, 'Airport departure',
                'airport departure', %(session_a)s, 'active', %(coordinator_a)s,
                now() - interval '2 hours', now() - interval '1 hour',
                now() - interval '1 hour'
            );

            INSERT INTO attendance_records (
                id, agency_id, session_id, passenger_id, coordinator_user_id,
                scanned_at, sync_source, client_event_id, device_id, created_at
            )
            VALUES (
                %(attendance_a)s, %(agency_a)s, %(session_a)s, %(passenger_a)s,
                %(coordinator_a)s, now() - interval '30 minutes', 'offline',
                'ci-rehearsal-event-1', 'synthetic-device', now() - interval '29 minutes'
            );

            INSERT INTO attendance_closeout_checkpoints (
                id, session_id, coordinator_user_id, pending_count, sending_count,
                retryable_count, needs_review_count, unreviewed_rejected_count,
                oldest_pending_age_seconds, reported_at
            )
            VALUES (
                %(closeout_a)s, %(session_a)s, %(coordinator_a)s, 2, 1, 1, 1, 0, 90, now()
            );

            INSERT INTO rooming_hotels (
                id, agency_id, group_id, hotel_name, city, created_by_user_id,
                created_at, updated_at, allocation_updated_at
            )
            VALUES (
                %(hotel_a)s, %(agency_a)s, %(group_a)s, 'CI Rehearsal Hotel', 'Delhi',
                %(admin_a)s, now() - interval '7 days', now() - interval '6 days',
                now() - interval '5 days'
            );

            INSERT INTO gc_group_access (
                id, agency_id, group_id, is_enabled, passenger_access_enabled,
                coordinator_access_enabled, created_by_user_id, updated_by_user_id
            )
            VALUES
                (%(gc_access_a)s, %(agency_a)s, %(group_a)s, true, true, true,
                 %(admin_a)s, %(admin_a)s),
                (%(gc_access_b)s, %(agency_b)s, %(group_b)s, true, false, true,
                 %(coordinator_b)s, %(coordinator_b)s);

            INSERT INTO audit_logs (
                id, agency_id, user_id, actor_email, action, entity_type,
                entity_id, metadata, created_at
            )
            VALUES (
                %(audit_a)s, %(agency_a)s, %(admin_a)s, 'admin-a@example.invalid',
                'ci.rehearsal.seeded', 'client_group', %(group_a)s::text,
                '{"synthetic": true, "purpose": "restore-upgrade-rehearsal"}'::jsonb, now()
            );

            INSERT INTO identity_action_tokens (
                id, user_id, purpose, token_hash, expires_at, created_by_user_id,
                request_ip_hash, created_at
            )
            VALUES (
                %(identity_token_a)s, %(coordinator_a)s, 'activation',
                repeat('a', 64), now() + interval '1 day', %(admin_a)s,
                repeat('b', 64), now()
            );
            """,
            IDS,
        )
    connection.commit()


def _scalar(connection: Connection, statement: str, parameters: object = None) -> Any:
    with connection.cursor() as cursor:
        cursor.execute(statement, parameters)
        row = cursor.fetchone()
    if row is None:
        raise AssertionError(f"Query returned no row: {statement}")
    return row[0]


def _row_counts(connection: Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    with connection.cursor() as cursor:
        for table_name in PRESERVED_TABLES:
            cursor.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table_name))
            )
            row = cursor.fetchone()
            assert row is not None
            counts[table_name] = int(row[0])
    return counts


def _previous_release_snapshot(connection: Connection) -> dict[str, Any]:
    return {
        "revision": _revision(connection),
        "row_counts": _row_counts(connection),
        "attendance_client_event": _scalar(
            connection,
            "SELECT client_event_id FROM attendance_records WHERE id = %s",
            (IDS["attendance_a"],),
        ),
        "closeout_counts": _scalar(
            connection,
            "SELECT concat_ws(':', pending_count, sending_count, retryable_count, "
            "needs_review_count) FROM attendance_closeout_checkpoints WHERE id = %s",
            (IDS["closeout_a"],),
        ),
        "group_retention_days": _scalar(
            connection,
            "SELECT passport_retention_days_applied FROM client_groups WHERE id = %s",
            (IDS["group_a"],),
        ),
        "hotel_updated_at": _scalar(
            connection,
            "SELECT updated_at::text FROM rooming_hotels WHERE id = %s",
            (IDS["hotel_a"],),
        ),
        "passport_number": _scalar(
            connection,
            "SELECT confirmed_fields ->> 'passport_number' "
            "FROM passport_submissions WHERE id = %s",
            (IDS["passenger_a"],),
        ),
    }


def _assert_snapshot_equal(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> None:
    if dict(expected) != dict(actual):
        raise AssertionError(
            "Restored 0085 data differs from the source snapshot:\n"
            + json.dumps({"expected": expected, "actual": actual}, indent=2, sort_keys=True)
        )


def _assert_constraint_rejected(
    connection: Connection,
    *,
    statement: str,
    parameters: object,
    expected_constraint: str | None = None,
    expected_sqlstate: str | None = None,
) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SAVEPOINT expected_rehearsal_failure")
        try:
            cursor.execute(statement, parameters)
        except psycopg2.Error as error:
            constraint_name = error.diag.constraint_name
            sqlstate = error.pgcode
            cursor.execute("ROLLBACK TO SAVEPOINT expected_rehearsal_failure")
            cursor.execute("RELEASE SAVEPOINT expected_rehearsal_failure")
            if expected_constraint is not None and constraint_name != expected_constraint:
                raise AssertionError(
                    f"Expected constraint {expected_constraint!r}, got {constraint_name!r}"
                ) from error
            if expected_sqlstate is not None and sqlstate != expected_sqlstate:
                raise AssertionError(
                    f"Expected SQLSTATE {expected_sqlstate!r}, got {sqlstate!r}"
                ) from error
            return constraint_name or sqlstate or "rejected"
        cursor.execute("ROLLBACK TO SAVEPOINT expected_rehearsal_failure")
        cursor.execute("RELEASE SAVEPOINT expected_rehearsal_failure")
    raise AssertionError("Database accepted a row that the reviewed head must reject")


def _verify_upgraded_database(connection: Connection) -> dict[str, Any]:
    if _revision(connection) != EXPECTED_HEAD_REVISION:
        raise AssertionError("Restored database did not reach the reviewed merge head")

    expected_counts = {
        "agencies": 2,
        "users": 3,
        "user_security_states": 3,
        "client_groups": 2,
        "passport_submissions": 1,
        "attendance_sessions": 1,
        "attendance_records": 1,
        "attendance_closeout_checkpoints": 1,
        "rooming_hotels": 1,
        "gc_group_access": 2,
        "audit_logs": 1,
        "identity_action_tokens": 1,
    }
    actual_counts = _row_counts(connection)
    if actual_counts != expected_counts:
        raise AssertionError(f"Head row counts changed: {actual_counts!r}")

    backfills = {
        "closeout_agency": str(
            _scalar(
                connection,
                "SELECT agency_id FROM attendance_closeout_checkpoints WHERE id = %s",
                (IDS["closeout_a"],),
            )
        ),
        "closeout_runtime_is_null": bool(
            _scalar(
                connection,
                "SELECT runtime_registration_id IS NULL "
                "FROM attendance_closeout_checkpoints WHERE id = %s",
                (IDS["closeout_a"],),
            )
        ),
        "session_schedule_version": int(
            _scalar(
                connection,
                "SELECT schedule_version FROM attendance_sessions WHERE id = %s",
                (IDS["session_a"],),
            )
        ),
        "record_runtime_is_null": bool(
            _scalar(
                connection,
                "SELECT runtime_registration_id IS NULL FROM attendance_records WHERE id = %s",
                (IDS["attendance_a"],),
            )
        ),
        "identity_token_key_id": _scalar(
            connection,
            "SELECT token_key_id FROM identity_action_tokens WHERE id = %s",
            (IDS["identity_token_a"],),
        ),
        "legacy_audit_shape": _scalar(
            connection,
            "SELECT concat_ws(':', result, integrity_version, "
            "(integrity_scope IS NULL)::text, (entry_hash IS NULL)::text) "
            "FROM audit_logs WHERE id = %s",
            (IDS["audit_a"],),
        ),
    }
    expected_backfills = {
        "closeout_agency": IDS["agency_a"],
        "closeout_runtime_is_null": True,
        "session_schedule_version": 1,
        "record_runtime_is_null": True,
        "identity_token_key_id": "legacy-v1",
        "legacy_audit_shape": "success:0:true:true",
    }
    if backfills != expected_backfills:
        raise AssertionError(f"Backfill verification failed: {backfills!r}")

    new_tables = (
        "my_photo_galleries",
        "my_photo_media_assets",
        "attendance_runtime_registrations",
        "attendance_scan_batches",
        "attendance_discard_tombstones",
        "identity_notification_outbox",
        "untrusted_upload_scans",
        "audit_chain_heads",
    )
    for table_name in new_tables:
        if _scalar(connection, "SELECT to_regclass(%s) IS NOT NULL", (table_name,)) is not True:
            raise AssertionError(f"Expected head table {table_name!r} is missing")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO my_photo_galleries (
                id, agency_id, group_id, gc_group_access_id, feature_enabled, status
            )
            VALUES (%s, %s, %s, %s, false, 'not_uploaded')
            """,
            (
                IDS["gallery_a"],
                IDS["agency_a"],
                IDS["group_a"],
                IDS["gc_access_a"],
            ),
        )
    connection.commit()

    constraints = {
        "schedule_version": _assert_constraint_rejected(
            connection,
            statement="UPDATE attendance_sessions SET schedule_version = 0 WHERE id = %s",
            parameters=(IDS["session_a"],),
            expected_constraint="ck_attendance_sessions_schedule_version",
        ),
        "cross_tenant_closeout": _assert_constraint_rejected(
            connection,
            statement="""
                INSERT INTO attendance_closeout_checkpoints (
                    id, session_id, coordinator_user_id, agency_id, pending_count,
                    sending_count, retryable_count, needs_review_count,
                    unreviewed_rejected_count, oldest_pending_age_seconds, reported_at
                ) VALUES (%s, %s, %s, %s, 0, 0, 0, 0, 0, NULL, now())
            """,
            parameters=(
                IDS["invalid_closeout"],
                IDS["session_a"],
                IDS["coordinator_b"],
                IDS["agency_b"],
            ),
            expected_constraint="fk_attendance_closeout_session_tenant",
        ),
        "my_photos_ready_shape": _assert_constraint_rejected(
            connection,
            statement="""
                INSERT INTO my_photo_galleries (
                    id, agency_id, group_id, gc_group_access_id, feature_enabled, status
                ) VALUES (%s, %s, %s, %s, true, 'ready')
            """,
            parameters=(
                IDS["invalid_gallery"],
                IDS["agency_b"],
                IDS["group_b"],
                IDS["gc_access_b"],
            ),
            expected_constraint="ck_my_photo_gallery_ready_shape",
        ),
        "audit_append_only": _assert_constraint_rejected(
            connection,
            statement="UPDATE audit_logs SET action = 'ci.rehearsal.tampered' WHERE id = %s",
            parameters=(IDS["audit_a"],),
            expected_sqlstate="55000",
        ),
    }
    connection.commit()

    return {
        "revision": _revision(connection),
        "preserved_row_counts": actual_counts,
        "backfills": backfills,
        "new_tables": list(new_tables),
        "verified_constraints": constraints,
        "positive_my_photos_gallery_count": int(
            _scalar(connection, "SELECT count(*) FROM my_photo_galleries")
        ),
    }


def _client_major(version_output: str) -> int:
    match = re.search(r"\b(\d+)(?:\.\d+)?\b", version_output)
    if match is None:
        raise ValueError(f"Could not parse PostgreSQL client version from {version_output!r}")
    return int(match.group(1))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timed_stage(timings: dict[str, float], name: str, operation: Any) -> Any:
    started = time.monotonic()
    try:
        return operation()
    finally:
        timings[name] = round(time.monotonic() - started, 3)


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
            server_major = int(
                _scalar(source_connection, "SELECT current_setting('server_version_num')")
            ) // 10000
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-database",
        default="passdetection_ci_previous_release",
    )
    parser.add_argument(
        "--restored-database",
        default="passdetection_ci_restored_release",
    )
    parser.add_argument(
        "--evidence-output",
        type=Path,
        default=Path("migration-rehearsal-evidence.json"),
    )
    return parser.parse_args()


def main() -> None:
    arguments = _parse_args()
    backend_root = Path(__file__).resolve().parents[1]
    rehearse(
        backend_root=backend_root,
        evidence_output=arguments.evidence_output.resolve(),
        source_database=arguments.source_database,
        restored_database=arguments.restored_database,
    )


if __name__ == "__main__":
    main()
