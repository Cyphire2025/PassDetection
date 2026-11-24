"""A stale deletion result cannot consume or release a newer durable claim."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.infrastructure.database.my_photos_models import MyPhotoEnrollmentModel
from app.infrastructure.my_photos import recovery_runtime
from tests.integration.test_my_photos_provider_claim_freshness import (
    photo_database as photo_database,
)


@pytest.mark.parametrize("kind", ["current", "superseded"])
@pytest.mark.parametrize("complete", [False, True])
async def test_late_provider_deletion_outcome_cannot_finalize_newer_claim(
    photo_database,
    monkeypatch,
    kind,
    complete,
):
    env = photo_database
    monkeypatch.setattr(recovery_runtime, "AsyncSessionFactory", env.sessions)
    now = datetime.now(UTC)
    async with env.sessions() as session, session.begin():
        enrollment = await session.scalar(select(MyPhotoEnrollmentModel))
        enrollment_id = enrollment.id
        enrollment.provider_name = "development"
        enrollment.provider_reference_handle = "synthetic-current-reference"
        enrollment.reference_version = 2
        enrollment.enrolled_at = now
        if kind == "current":
            enrollment.status = "deleted"
            enrollment.deleted_at = now
            enrollment.deletion_idempotency_key = "synthetic-delete"
            enrollment.deletion_scope = "enrollment_only"
            enrollment.provider_deletion_status = "pending"
            enrollment.provider_deletion_requested_at = now
        else:
            enrollment.status = "enrolled"
            enrollment.superseded_provider_reference_handle = "synthetic-old-reference"
            enrollment.superseded_reference_deletion_status = "pending"
            enrollment.superseded_reference_deletion_requested_at = now

    (first,) = await recovery_runtime._claim_provider_deletions(env.settings)
    next_field = (
        "provider_deletion_next_attempt_at"
        if kind == "current"
        else "superseded_deletion_next_attempt_at"
    )
    status_field = (
        "provider_deletion_status" if kind == "current" else "superseded_reference_deletion_status"
    )
    async with env.sessions() as session, session.begin():
        enrollment = await session.get(MyPhotoEnrollmentModel, enrollment_id)
        setattr(enrollment, next_field, now - timedelta(seconds=1))
    (second,) = await recovery_runtime._claim_provider_deletions(env.settings)
    assert first.attempt_count == 1 and second.attempt_count == 2
    async with env.sessions() as session:
        enrollment = await session.get(MyPhotoEnrollmentModel, enrollment_id)
        second_deadline = getattr(enrollment, next_field)

    stale = recovery_runtime._DeletionOutcome(
        first, complete, None if complete else "PROVIDER_UNAVAILABLE"
    )
    result = await recovery_runtime._finalize_provider_deletions([stale], env.settings)
    assert (result.completed, result.retrying, result.terminal_failed) == (0, 0, 0)
    async with env.sessions() as session:
        enrollment = await session.get(MyPhotoEnrollmentModel, enrollment_id)
        assert getattr(enrollment, status_field) == "pending"
        assert getattr(enrollment, next_field) == second_deadline

    current = recovery_runtime._DeletionOutcome(second, True, None)
    result = await recovery_runtime._finalize_provider_deletions([current], env.settings)
    assert result.completed == 1
    async with env.sessions() as session:
        enrollment = await session.get(MyPhotoEnrollmentModel, enrollment_id)
        assert getattr(enrollment, status_field) == "complete"
