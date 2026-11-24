"""PostgreSQL synthetic rehearsal snapshot owner."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

from scripts.postgresql_rehearsal_contract import IDS, PRESERVED_TABLES


def _revision(connection: Connection) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        rows = cursor.fetchall()
    if len(rows) != 1:
        raise AssertionError(f"Expected one Alembic head row, found {rows!r}")
    return str(rows[0][0])


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
            cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table_name)))
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
            "SELECT confirmed_fields ->> 'passport_number' FROM passport_submissions WHERE id = %s",
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


# Preserve canonical public import/pickle identities through the CLI facade.
for _export in (
    _revision,
    _scalar,
    _row_counts,
    _previous_release_snapshot,
    _assert_snapshot_equal,
    _assert_constraint_rejected,
):
    _export.__module__ = "scripts.rehearse_postgresql_upgrade"
del _export
