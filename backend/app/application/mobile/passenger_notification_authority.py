"""Read-only, batched submitted-contact checks for background push workers."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.application.mobile.passenger_phone_authority import submitted_phone_matches_identity
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobilePassengerIdentityModel,
    MobilePassengerSessionIdentityModel,
)
from app.infrastructure.database.models import PassportSubmissionModel

_PAGE_SIZE = 250
_SUBMISSION_FIELDS = (
    PassportSubmissionModel.id,
    PassportSubmissionModel.agency_id,
    PassportSubmissionModel.group_id,
    PassportSubmissionModel.status,
    PassportSubmissionModel.client_phone,
    PassportSubmissionModel.client_reviewed_at,
    PassportSubmissionModel.staff_metadata,
    PassportSubmissionModel.confidence_score,
    PassportSubmissionModel.image_s3_key,
)


async def authoritative_passenger_ids(
    session: AsyncSession,
    recipient_ids: Sequence[uuid.UUID],
    *,
    access: GCGroupAccessModel | None = None,
) -> set[uuid.UUID]:
    allowed: set[uuid.UUID] = set()
    for offset in range(0, len(recipient_ids), _PAGE_SIZE):
        statement = (
            select(MobilePassengerIdentityModel, PassportSubmissionModel)
            .join(
                PassportSubmissionModel,
                PassportSubmissionModel.id == MobilePassengerIdentityModel.passenger_submission_id,
            )
            .options(load_only(*_SUBMISSION_FIELDS))
            .where(
                MobilePassengerIdentityModel.id.in_(recipient_ids[offset : offset + _PAGE_SIZE]),
                MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
                MobilePassengerIdentityModel.revoked_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        if access is not None:
            statement = statement.where(
                MobilePassengerIdentityModel.agency_id == access.agency_id,
                MobilePassengerIdentityModel.group_id == access.group_id,
                MobilePassengerIdentityModel.gc_group_access_id == access.id,
            )
        for identity, submission in (await session.execute(statement)).all():
            if submitted_phone_matches_identity(identity, submission):
                allowed.add(identity.id)
    return allowed


async def retain_recipient_ids(
    session: AsyncSession,
    *,
    recipient_ids: Sequence[uuid.UUID],
    recipient_type: str,
    access: GCGroupAccessModel,
) -> list[uuid.UUID]:
    if recipient_type != "passenger":
        return list(recipient_ids)
    allowed = await authoritative_passenger_ids(session, recipient_ids, access=access)
    return [item for item in recipient_ids if item in allowed]


async def authoritative_passenger_device_ids(
    session: AsyncSession,
    devices: Sequence[MobileDeviceSessionModel],
) -> set[uuid.UUID]:
    """Check the selected identity grant without revoking or committing sessions."""
    selected = {device.id: device for device in devices if device.subject_role == "passenger"}
    allowed: set[uuid.UUID] = set()
    ids = list(selected)
    for offset in range(0, len(ids), _PAGE_SIZE):
        rows = (
            await session.execute(
                select(
                    MobilePassengerSessionIdentityModel,
                    MobilePassengerIdentityModel,
                    PassportSubmissionModel,
                )
                .join(
                    MobilePassengerIdentityModel,
                    MobilePassengerIdentityModel.id
                    == MobilePassengerSessionIdentityModel.passenger_identity_id,
                )
                .join(
                    PassportSubmissionModel,
                    PassportSubmissionModel.id
                    == MobilePassengerIdentityModel.passenger_submission_id,
                )
                .options(load_only(*_SUBMISSION_FIELDS))
                .where(
                    MobilePassengerSessionIdentityModel.session_id.in_(
                        ids[offset : offset + _PAGE_SIZE]
                    ),
                    MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
                    MobilePassengerIdentityModel.revoked_at.is_(None),
                )
                .execution_options(populate_existing=True)
            )
        ).all()
        for binding, identity, submission in rows:
            device = selected[binding.session_id]
            if (
                device.passenger_identity_id == identity.id
                and device.agency_id == binding.agency_id == identity.agency_id
                and binding.group_id == identity.group_id
                and binding.gc_group_access_id == identity.gc_group_access_id
                and binding.identity_claim_generation == identity.claim_generation
                and submitted_phone_matches_identity(identity, submission)
            ):
                allowed.add(device.id)
    return allowed
