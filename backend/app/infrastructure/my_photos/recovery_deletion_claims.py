"""Claim bounded due provider deletions under durable enrollment locks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select

from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import MyPhotoEnrollmentModel
from app.infrastructure.my_photos.recovery_contracts import (
    DeletionKind,
    RecoveryContext,
    _DeletionClaim,
)
from app.infrastructure.my_photos.recovery_deletion_policy import _due


async def _claim_provider_deletions(
    ctx: RecoveryContext, settings: Settings
) -> tuple[_DeletionClaim, ...]:
    now = datetime.now(tz=UTC)
    async with ctx.sessions() as session:
        enrollments = list(
            (
                await session.execute(
                    select(MyPhotoEnrollmentModel)
                    .where(
                        or_(
                            and_(
                                MyPhotoEnrollmentModel.status == "deleted",
                                MyPhotoEnrollmentModel.provider_deletion_attempt_count
                                < settings.my_photos.provider_deletion_max_attempts,
                                or_(
                                    MyPhotoEnrollmentModel.provider_deletion_next_attempt_at.is_(
                                        None
                                    ),
                                    MyPhotoEnrollmentModel.provider_deletion_next_attempt_at <= now,
                                ),
                                MyPhotoEnrollmentModel.provider_deletion_status.in_(
                                    ("pending", "failed")
                                ),
                                MyPhotoEnrollmentModel.provider_reference_handle.is_not(None),
                                MyPhotoEnrollmentModel.deletion_idempotency_key.is_not(None),
                            ),
                            and_(
                                MyPhotoEnrollmentModel.superseded_deletion_attempt_count
                                < settings.my_photos.provider_deletion_max_attempts,
                                or_(
                                    MyPhotoEnrollmentModel.superseded_deletion_next_attempt_at.is_(
                                        None
                                    ),
                                    MyPhotoEnrollmentModel.superseded_deletion_next_attempt_at
                                    <= now,
                                ),
                                MyPhotoEnrollmentModel.superseded_reference_deletion_status.in_(
                                    ("pending", "failed")
                                ),
                                MyPhotoEnrollmentModel.superseded_provider_reference_handle.is_not(
                                    None
                                ),
                            ),
                        ),
                    )
                    .order_by(
                        MyPhotoEnrollmentModel.updated_at,
                        MyPhotoEnrollmentModel.id,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(settings.my_photos.provider_deletion_batch_size)
                )
            ).scalars()
        )
        claims: list[_DeletionClaim] = []
        for enrollment in enrollments:
            if (
                enrollment.superseded_reference_deletion_status in {"pending", "failed"}
                and enrollment.superseded_provider_reference_handle is not None
                and enrollment.superseded_deletion_attempt_count
                < settings.my_photos.provider_deletion_max_attempts
                and _due(enrollment.superseded_deletion_next_attempt_at, now)
            ):
                kind: DeletionKind = "superseded"
                provider_reference = enrollment.superseded_provider_reference_handle
                deletion_identity = (
                    f"supersede:{enrollment.id}:{max(enrollment.reference_version - 1, 0)}"
                )
                enrollment.superseded_reference_deletion_status = "pending"
                enrollment.superseded_deletion_attempt_count += 1
                enrollment.superseded_deletion_last_attempt_at = now
                enrollment.superseded_deletion_next_attempt_at = now + timedelta(
                    seconds=settings.my_photos.provider_deletion_claim_seconds
                )
                attempt_count = enrollment.superseded_deletion_attempt_count
            elif (
                enrollment.status == "deleted"
                and enrollment.provider_deletion_status in {"pending", "failed"}
                and enrollment.provider_reference_handle is not None
                and enrollment.deletion_idempotency_key is not None
                and enrollment.provider_deletion_attempt_count
                < settings.my_photos.provider_deletion_max_attempts
                and _due(enrollment.provider_deletion_next_attempt_at, now)
            ):
                kind = "current"
                provider_reference = enrollment.provider_reference_handle
                deletion_identity = enrollment.deletion_idempotency_key
                enrollment.provider_deletion_status = "pending"
                enrollment.provider_deletion_attempt_count += 1
                enrollment.provider_deletion_last_attempt_at = now
                enrollment.provider_deletion_next_attempt_at = now + timedelta(
                    seconds=settings.my_photos.provider_deletion_claim_seconds
                )
                attempt_count = enrollment.provider_deletion_attempt_count
            else:
                continue
            claims.append(
                _DeletionClaim(
                    enrollment_id=enrollment.id,
                    kind=kind,
                    agency_id=enrollment.agency_id,
                    group_id=enrollment.group_id,
                    passenger_identity_id=enrollment.passenger_identity_id,
                    provider_reference=provider_reference,
                    deletion_identity=deletion_identity,
                    attempt_count=attempt_count,
                )
            )
        await session.commit()
        return tuple(claims)
