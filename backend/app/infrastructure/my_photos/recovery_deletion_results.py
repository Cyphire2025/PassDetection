"""Finalize only the current durable deletion attempt and reference."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import MyPhotoEnrollmentModel
from app.infrastructure.my_photos.audit import record_my_photos_audit
from app.infrastructure.my_photos.recovery_contracts import (
    ProviderDeletionBatchResult,
    RecoveryContext,
    _DeletionOutcome,
)
from app.infrastructure.my_photos.recovery_deletion_policy import (
    _complete_reference,
    _deletion_retry_delay,
    _fail_reference,
    _pending_reference,
    _reference_unchanged,
    _set_next_attempt,
)


async def _finalize_provider_deletions(
    ctx: RecoveryContext,
    outcomes: tuple[_DeletionOutcome, ...] | list[_DeletionOutcome],
    settings: Settings,
) -> ProviderDeletionBatchResult:
    completed = 0
    retrying = 0
    terminal_failed = 0
    if not outcomes:
        return ProviderDeletionBatchResult(0, 0, 0, 0)
    ids = tuple(outcome.claim.enrollment_id for outcome in outcomes)
    async with ctx.sessions() as session:
        rows = {
            row.id: row
            for row in (
                (
                    await session.execute(
                        select(MyPhotoEnrollmentModel)
                        .where(MyPhotoEnrollmentModel.id.in_(ids))
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
        }
        now = datetime.now(tz=UTC)
        for outcome in outcomes:
            enrollment = rows.get(outcome.claim.enrollment_id)
            if enrollment is None or not _reference_unchanged(enrollment, outcome.claim):
                continue
            if outcome.complete:
                _complete_reference(enrollment, outcome.claim.kind, now)
                completed += 1
            elif outcome.claim.attempt_count >= settings.my_photos.provider_deletion_max_attempts:
                _fail_reference(enrollment, outcome.claim.kind, outcome.error_code)
                _set_next_attempt(enrollment, outcome.claim.kind, None)
                terminal_failed += 1
            else:
                _pending_reference(enrollment, outcome.claim.kind, outcome.error_code)
                _set_next_attempt(
                    enrollment,
                    outcome.claim.kind,
                    now + timedelta(seconds=_deletion_retry_delay(outcome.claim, settings)),
                )
                retrying += 1
            await record_my_photos_audit(
                session,
                action="my_photos_provider_deletion",
                agency_id=enrollment.agency_id,
                group_id=enrollment.group_id,
                outcome=(
                    f"{outcome.claim.kind}_complete"
                    if outcome.complete
                    else f"{outcome.claim.kind}_failed"
                    if outcome.claim.attempt_count
                    >= settings.my_photos.provider_deletion_max_attempts
                    else f"{outcome.claim.kind}_pending"
                ),
            )
        await session.commit()
    return ProviderDeletionBatchResult(len(outcomes), completed, retrying, terminal_failed)
