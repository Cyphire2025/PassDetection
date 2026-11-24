"""QR delivery policy and deterministic stale recovery."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import (
    User,
    UserRole,
)
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassengerQrWhatsAppDeliveryModel,
)

QR_DELIVERY_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
]


ACCEPTED_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})


IN_PROGRESS_STATUSES = frozenset({"queued", "processing", "delivery_unknown"})


QR_QUEUED_STALE_AFTER = timedelta(minutes=2)


QR_PROCESSING_STALE_AFTER = timedelta(minutes=10)


AMBIGUOUS_PRIVATE_DESTINATION_REASON = (
    "A WhatsApp destination is shared by multiple passengers. Correct the "
    "recipient numbers before sending private QR codes."
)


def _agency_id(current_user: User) -> uuid.UUID:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not assigned to an agency",
        )
    return current_user.agency_id


async def _manageable_group(
    session: AsyncSession,
    *,
    current_user: User,
    group_id: uuid.UUID,
) -> ClientGroupModel:
    agency_id = _agency_id(current_user)
    result = await session.execute(
        select(ClientGroupModel).where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.status != "deleted",
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group was not found",
        )
    try:
        await AuthorizationPolicy(session).require_assign_coordinator(
            current_user,
            group,
        )
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc
    return group


async def _recover_stale_qr_deliveries(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    now: datetime | None = None,
) -> int:
    """Recover only states whose provider-safety outcome is deterministic."""

    recovered_at = now or datetime.now(tz=UTC)
    queued_result = await session.execute(
        update(PassengerQrWhatsAppDeliveryModel)
        .where(
            PassengerQrWhatsAppDeliveryModel.agency_id == group.agency_id,
            PassengerQrWhatsAppDeliveryModel.group_id == group.id,
            PassengerQrWhatsAppDeliveryModel.status == "queued",
            PassengerQrWhatsAppDeliveryModel.status_updated_at
            <= recovered_at - QR_QUEUED_STALE_AFTER,
        )
        .values(
            status="failed",
            status_updated_at=recovered_at,
            updated_at=recovered_at,
            error_message=(
                "WHATSAPP_QUEUE_INTERRUPTED: No worker claimed this queued QR "
                "delivery; retrying it is safe"
            ),
        )
        .execution_options(synchronize_session=False)
    )
    uncertain_result = await session.execute(
        update(PassengerQrWhatsAppDeliveryModel)
        .where(
            PassengerQrWhatsAppDeliveryModel.agency_id == group.agency_id,
            PassengerQrWhatsAppDeliveryModel.group_id == group.id,
            PassengerQrWhatsAppDeliveryModel.status == "processing",
            PassengerQrWhatsAppDeliveryModel.status_updated_at
            <= recovered_at - QR_PROCESSING_STALE_AFTER,
        )
        .values(
            status="delivery_unknown",
            status_updated_at=recovered_at,
            updated_at=recovered_at,
            error_message=(
                "WHATSAPP_DELIVERY_UNKNOWN: Provider processing was interrupted; "
                "automatic resend is suppressed"
            ),
        )
        .execution_options(synchronize_session=False)
    )
    return int(getattr(queued_result, "rowcount", 0) or 0) + int(
        getattr(uncertain_result, "rowcount", 0) or 0
    )
