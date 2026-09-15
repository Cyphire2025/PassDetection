"""Keep existing passenger sessions bound to current collection contacts."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.application.mobile.passenger_phone_authority import submitted_phone_matches_identity
from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel,
    MobilePassengerIdentityModel,
    MobilePassengerSessionIdentityModel,
    MobileRefreshTokenModel,
)
from app.infrastructure.database.models import PassportSubmissionModel

# OTP discovery grants at most fifty identities. Fetch one extra to fail closed
# if a corrupt or historical session exceeds the supported authorization bound.
MAX_SESSION_PASSENGER_IDENTITIES = 50


async def ensure_current_passenger_session_bindings(
    session: AsyncSession, device_session: MobileDeviceSessionModel,
) -> bool:
    """Validate every grant, including identities outside the selected trip.

    Healthy sessions perform one indexed, bounded read. A mismatch revokes this
    session and its refresh tokens before returning False; the caller must deny
    authentication. No replacement phone receives a grant from this operation.
    Identity reconciliation remains in the normal OTP/admin path, avoiding an
    access-row/session-row lock-order inversion during token refresh.
    """

    rows = list((await session.execute(
        select(
            MobilePassengerSessionIdentityModel,
            MobilePassengerIdentityModel,
            PassportSubmissionModel,
        )
        .outerjoin(MobilePassengerIdentityModel, and_(
            MobilePassengerIdentityModel.id
            == MobilePassengerSessionIdentityModel.passenger_identity_id,
            MobilePassengerIdentityModel.agency_id
            == MobilePassengerSessionIdentityModel.agency_id,
            MobilePassengerIdentityModel.group_id
            == MobilePassengerSessionIdentityModel.group_id,
            MobilePassengerIdentityModel.gc_group_access_id
            == MobilePassengerSessionIdentityModel.gc_group_access_id,
        ))
        .outerjoin(PassportSubmissionModel, and_(
            PassportSubmissionModel.id == MobilePassengerIdentityModel.passenger_submission_id,
            PassportSubmissionModel.agency_id == MobilePassengerIdentityModel.agency_id,
            PassportSubmissionModel.group_id == MobilePassengerIdentityModel.group_id,
        ))
        .where(MobilePassengerSessionIdentityModel.session_id == device_session.id)
        .options(load_only(
            PassportSubmissionModel.id, PassportSubmissionModel.agency_id,
            PassportSubmissionModel.group_id, PassportSubmissionModel.client_phone,
            PassportSubmissionModel.status, PassportSubmissionModel.client_reviewed_at,
            PassportSubmissionModel.staff_metadata, PassportSubmissionModel.confidence_score,
            PassportSubmissionModel.image_s3_key,
        ))
        .execution_options(populate_existing=True)
        .limit(MAX_SESSION_PASSENGER_IDENTITIES + 1)
    )).all())
    valid = (
        0 < len(rows) <= MAX_SESSION_PASSENGER_IDENTITIES
        and all(
            binding.agency_id == device_session.agency_id
            and identity is not None
            and submission is not None
            and identity.status in {"eligible", "claimed"}
            and identity.revoked_at is None
            and identity.claim_generation == binding.identity_claim_generation
            and submitted_phone_matches_identity(identity, submission)
            for binding, identity, submission in rows
        )
        and any(
            binding.passenger_identity_id == device_session.passenger_identity_id
            and binding.group_id == device_session.selected_group_id
            and binding.gc_group_access_id == device_session.selected_gc_group_access_id
            for binding, _identity, _submission in rows
        )
    )
    if valid:
        return True
    now = datetime.now(UTC)
    reason = "passenger_collection_contact_changed"
    # Scope both mutations to the already authenticated device session. This
    # does not change identities, collection data, or another phone's sessions.
    await session.execute(
        update(MobileRefreshTokenModel)
        .where(
            MobileRefreshTokenModel.session_id == device_session.id,
            MobileRefreshTokenModel.agency_id == device_session.agency_id,
            MobileRefreshTokenModel.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoke_reason=reason)
    )
    if device_session.status == "active":
        device_session.status = "revoked"
        device_session.session_generation += 1
        device_session.revoked_at = now
        device_session.revoke_reason = reason
        device_session.updated_at = now
    # Authentication errors roll back the request transaction. Persist the
    # revocation first so a retry cannot revive the stale authorization.
    await session.commit()
    return False
