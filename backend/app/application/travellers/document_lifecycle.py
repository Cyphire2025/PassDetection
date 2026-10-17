"""Explicit unusable declarations revoke reuse without restoring older passports."""

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions.exceptions import ConflictError, EntityNotFoundError
from app.infrastructure.database.traveller_reuse_models import (
    TravellerChangeEventModel,
    TravellerPassportModel,
    TravellerProfileModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


async def block_passport(session: AsyncSession, *, profile: TravellerProfileModel,
    passport_id: uuid.UUID, expected_profile_revision: int, expected_passport_revision: int,
    status: Literal["lost", "cancelled", "compromised"], actor_id: uuid.UUID,
) -> None:
    if profile.revision != expected_profile_revision:
        raise ConflictError("Traveller changed. Refresh before updating this document.")
    passport = await session.scalar(select(TravellerPassportModel).where(
        TravellerPassportModel.id == passport_id, TravellerPassportModel.traveller_id == profile.id,
        TravellerPassportModel.agency_id == profile.agency_id, TravellerPassportModel.company_id == profile.company_id,
    ).with_for_update().execution_options(populate_existing=True))
    if passport is None:
        raise EntityNotFoundError("Passport", passport_id)
    if passport.revision != expected_passport_revision:
        raise ConflictError("Passport changed. Refresh before updating this document.")
    passport.status, passport.is_default = status, False
    passport.revision += 1
    profile.authorization_version += 1
    profile.revision += 1
    session.add(TravellerChangeEventModel(agency_id=profile.agency_id, company_id=profile.company_id,
        traveller_id=profile.id, event_type="document_blocked", aggregate_id=passport.id,
        aggregate_revision=passport.revision, idempotency_key=f"blocked:{passport.id}:{passport.revision}",
        reason_code=f"passport_{status}"))
    await AuditLogRepository(session).record(action="traveller.passport_blocked", entity_type="traveller_passport",
        entity_id=str(passport.id), agency_id=profile.agency_id, user_id=actor_id,
        metadata={"traveller_id": str(profile.id), "reason_code": status, "revision": passport.revision})
