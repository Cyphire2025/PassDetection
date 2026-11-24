"""PostgreSQL synthetic rehearsal verification owner."""

from __future__ import annotations

from typing import Any

from psycopg2.extensions import connection as Connection

from scripts.postgresql_rehearsal_contract import EXPECTED_HEAD_REVISION, IDS
from scripts.postgresql_rehearsal_snapshot import (
    _assert_constraint_rejected,
    _revision,
    _row_counts,
    _scalar,
)


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
        "travel_tracker",
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
        "cross_tenant_travel_tracker": _assert_constraint_rejected(
            connection,
            statement="""
                INSERT INTO travel_tracker (passenger_id, agency_id, group_id)
                VALUES (%s, %s, %s)
            """,
            parameters=(IDS["passenger_a"], IDS["agency_b"], IDS["group_b"]),
            expected_constraint="fk_travel_tracker_passenger_scope",
        ),
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
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO travel_tracker (passenger_id, agency_id, group_id) VALUES (%s, %s, %s)",
            (IDS["passenger_a"], IDS["agency_a"], IDS["group_a"]),
        )
        cursor.execute(
            "SELECT visa_applied, flight_booked FROM travel_tracker WHERE passenger_id = %s",
            (IDS["passenger_a"],),
        )
        if cursor.fetchone() != (False, False):
            raise AssertionError(
                "New tracker rows must default to unmarked visa and flight statuses"
            )
        cursor.execute(
            "UPDATE travel_tracker SET visa_applied = true, visa_updated_by = %s, visa_updated_at = now() WHERE passenger_id = %s",
            (IDS["admin_a"], IDS["passenger_a"]),
        )
        cursor.execute(
            "SELECT visa_applied, flight_booked, visa_updated_by::text, visa_updated_at IS NOT NULL FROM travel_tracker WHERE passenger_id = %s",
            (IDS["passenger_a"],),
        )
        if cursor.fetchone() != (True, False, IDS["admin_a"], True):
            raise AssertionError("Tracker visa attribution or independent flight state failed")
    connection.commit()

    return {
        "revision": _revision(connection),
        "preserved_row_counts": actual_counts,
        "backfills": backfills,
        "new_tables": list(new_tables),
        "verified_constraints": constraints,
        "travel_tracker": {
            "default_unmarked": True,
            "independent_visa_mark": True,
            "actor_attributed": True,
        },
        "positive_my_photos_gallery_count": int(
            _scalar(connection, "SELECT count(*) FROM my_photo_galleries")
        ),
    }


# Preserve canonical public import/pickle identities through the CLI facade.
for _export in (_verify_upgraded_database,):
    _export.__module__ = "scripts.rehearse_postgresql_upgrade"
del _export
