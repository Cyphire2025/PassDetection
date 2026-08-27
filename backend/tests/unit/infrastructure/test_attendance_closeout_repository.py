from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.infrastructure.database.models import AttendanceCloseoutCheckpointModel
from app.infrastructure.repositories.attendance_closeout_repository import (
    ATTENDANCE_CLOSEOUT_CHECKPOINT_TTL_SECONDS,
    AttendanceCloseoutAssignmentCheckpoint,
    AttendanceCloseoutCounts,
    classify_attendance_closeout,
)
from app.presentation.api.v1.schemas.attendance_closeout_schemas import (
    AttendanceCloseoutCheckpointRequest,
    AttendanceCloseRequest,
)


def _assignment(
    *,
    coordinator_id: uuid.UUID | None = None,
    assigned_at: datetime,
    reported_at: datetime | None,
    counts: AttendanceCloseoutCounts | None,
) -> AttendanceCloseoutAssignmentCheckpoint:
    return AttendanceCloseoutAssignmentCheckpoint(
        coordinator_id=coordinator_id or uuid.uuid4(),
        coordinator_name="Coordinator",
        assigned_at=assigned_at,
        reported_at=reported_at,
        counts=counts,
    )


def _counts(
    *,
    pending: int = 0,
    sending: int = 0,
    retryable: int = 0,
    needs_review: int = 0,
    rejected: int = 0,
    oldest: int | None = None,
) -> AttendanceCloseoutCounts:
    return AttendanceCloseoutCounts(
        pending_count=pending,
        sending_count=sending,
        retryable_count=retryable,
        needs_review_count=needs_review,
        unreviewed_rejected_count=rejected,
        oldest_pending_age_seconds=oldest,
    )


def test_recent_zero_report_is_ready_and_exact_ttl_boundary_is_accepted() -> None:
    now = datetime.now(tz=UTC)
    status = classify_attendance_closeout(
        [
            _assignment(
                assigned_at=now - timedelta(hours=1),
                reported_at=now - timedelta(seconds=ATTENDANCE_CLOSEOUT_CHECKPOINT_TTL_SECONDS),
                counts=_counts(),
            )
        ],
        activity_valid_after=now - timedelta(hours=1),
        now=now,
    )

    assert status.ready is True
    assert status.ready_assignment_count == 1
    assert status.blocked_assignment_count == 0


def test_zero_assignments_fail_closed_without_affirmative_evidence() -> None:
    now = datetime.now(tz=UTC)
    status = classify_attendance_closeout(
        [],
        activity_valid_after=now - timedelta(minutes=5),
        now=now,
    )

    assert status.ready is False
    assert status.active_assignment_count == 0
    assert status.blocked_assignment_count == 0


@pytest.mark.parametrize(
    ("reported_at", "assigned_at_delta", "expected_state"),
    [
        (None, timedelta(hours=-1), "missing"),
        (
            timedelta(
                seconds=-ATTENDANCE_CLOSEOUT_CHECKPOINT_TTL_SECONDS,
                microseconds=-1,
            ),
            timedelta(hours=-1),
            "stale",
        ),
        (timedelta(seconds=-121), timedelta(hours=-1), "stale"),
        (timedelta(minutes=-2), timedelta(minutes=-1), "stale"),
    ],
)
def test_missing_expired_and_pre_assignment_reports_block(
    reported_at: timedelta | None,
    assigned_at_delta: timedelta,
    expected_state: str,
) -> None:
    now = datetime.now(tz=UTC)
    status = classify_attendance_closeout(
        [
            _assignment(
                assigned_at=now + assigned_at_delta,
                reported_at=now + reported_at if reported_at is not None else None,
                counts=_counts() if reported_at is not None else None,
            )
        ],
        activity_valid_after=now - timedelta(hours=1),
        now=now,
    )

    assert status.ready is False
    assert status.coordinators[0].state == expected_state


@pytest.mark.parametrize(
    "counts",
    [
        _counts(pending=1, oldest=7),
        _counts(sending=1, oldest=7),
        _counts(retryable=1, oldest=7),
        _counts(needs_review=1),
        _counts(rejected=1),
    ],
)
def test_every_unresolved_queue_class_blocks(counts: AttendanceCloseoutCounts) -> None:
    now = datetime.now(tz=UTC)
    status = classify_attendance_closeout(
        [
            _assignment(
                assigned_at=now - timedelta(hours=1),
                reported_at=now - timedelta(seconds=5),
                counts=counts,
            )
        ],
        activity_valid_after=now - timedelta(hours=1),
        now=now,
    )

    assert status.ready is False
    assert status.coordinators[0].state == "blocked"
    assert status.unresolved_count == 1


def test_oldest_pending_age_advances_from_server_report_time() -> None:
    now = datetime.now(tz=UTC)
    status = classify_attendance_closeout(
        [
            _assignment(
                assigned_at=now - timedelta(hours=1),
                reported_at=now - timedelta(seconds=9),
                counts=_counts(pending=1, oldest=41),
            )
        ],
        activity_valid_after=now - timedelta(hours=1),
        now=now,
    )

    assert status.oldest_pending_age_seconds == 50
    assert status.coordinators[0].oldest_pending_age_seconds == 50


def test_checkpoint_schema_is_count_only_and_rejects_extra_identity_data() -> None:
    approved_fields = {
        "pending_count",
        "sending_count",
        "retryable_count",
        "needs_review_count",
        "unreviewed_rejected_count",
        "oldest_pending_age_seconds",
        # A server-issued opaque runtime identifier is coordination evidence,
        # not passenger or queued-scan identity data.
        "runtime_id",
    }
    assert set(AttendanceCloseoutCheckpointRequest.model_fields) == approved_fields

    with pytest.raises(ValidationError, match="Extra inputs"):
        AttendanceCloseoutCheckpointRequest(
            pending_count=0,
            sending_count=0,
            retryable_count=0,
            needs_review_count=0,
            unreviewed_rejected_count=0,
            oldest_pending_age_seconds=None,
            passenger_id=str(uuid.uuid4()),  # type: ignore[call-arg]
        )


def test_exception_reason_is_bounded_normalized_and_extra_fields_are_forbidden() -> None:
    request = AttendanceCloseRequest(exception_reason="  approved   operations emergency  ")
    assert request.exception_reason == "approved operations emergency"

    with pytest.raises(ValidationError):
        AttendanceCloseRequest(exception_reason="too short")
    with pytest.raises(ValidationError):
        AttendanceCloseRequest(
            exception_reason="approved operations emergency",
            passenger_name="Asha",  # type: ignore[call-arg]
        )


def test_migration_and_model_store_only_privacy_bounded_checkpoint_fields() -> None:
    migration = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0083_attendance_closeout_checkpoints.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision = "0082_canonical_trip_timezone"' in migration
    assert "uq_attendance_closeout_checkpoint_coordinator" in migration
    assert "ck_attendance_closeout_checkpoint_oldest_pending" in migration
    enterprise_migration = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0087_enterprise_hardening.py"
    ).read_text(encoding="utf-8")
    assert "uq_attendance_closeout_checkpoint_runtime" in enterprise_migration
    assert "uq_attendance_closeout_legacy_account" in enterprise_migration
    assert "fk_attendance_closeout_runtime_tenant_coordinator" in enterprise_migration

    columns = set(AttendanceCloseoutCheckpointModel.__table__.columns.keys())
    assert columns == {
        "id",
        "session_id",
        "agency_id",
        "coordinator_user_id",
        "runtime_registration_id",
        "pending_count",
        "sending_count",
        "retryable_count",
        "needs_review_count",
        "unreviewed_rejected_count",
        "oldest_pending_age_seconds",
        "reported_at",
    }
    lowered = migration.lower()
    for forbidden in ("passenger_id", "qr_payload", "client_event", "device_id", "ip_address"):
        assert forbidden not in lowered

    enterprise_tree = ast.parse(enterprise_migration)
    closeout_migration_calls = "\n".join(
        segment
        for node in ast.walk(enterprise_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "op"
        and any(
            isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and "attendance_closeout_checkpoints" in value.value
            for value in ast.walk(node)
        )
        if (segment := ast.get_source_segment(enterprise_migration, node)) is not None
    )
    assert closeout_migration_calls
    lowered_enterprise = closeout_migration_calls.lower()
    for forbidden in ("passenger_id", "qr_payload", "client_event", "ip_address"):
        assert forbidden not in lowered_enterprise
