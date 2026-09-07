"""Authorized place resolution for the passenger trip globe."""

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.journey_destination import MobileJourneyDestinationResponse
from app.application.security.mobile_access_policy import MobileAccessPolicy
from app.core.security.mobile_jwt import MobileAccessClaims
from app.infrastructure.database.session import get_db_session
from app.infrastructure.mobile_journey_geocoding import (
    MobileJourneyGeocoder,
    get_mobile_journey_geocoder,
)
from app.presentation.dependencies.mobile_auth import require_unrestricted_mobile_claims

router = APIRouter()


@router.get(
    "/trips/{group_id}/journey-destination", response_model=MobileJourneyDestinationResponse
)
async def get_mobile_journey_destination(
    group_id: uuid.UUID,
    response: Response,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
    resolver: MobileJourneyGeocoder = Depends(get_mobile_journey_geocoder),
) -> MobileJourneyDestinationResponse:
    response.headers["Cache-Control"] = "private, no-store"
    trip = await MobileAccessPolicy(session).require_trip_access(claims, group_id)
    destination = trip.group.destination
    # Release this read-only transaction before waiting on Redis/network I/O.
    await session.rollback()
    return await resolver.resolve(destination)
