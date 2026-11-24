"""Prepare existing identity reconciliation and exact selected identity facts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_contracts import (
    _TARGETED_IDENTITY_CHANGE_LIMIT,
    MobilePassengerChangeKind,
)
from app.application.mobile.passenger_identity_reconciliation import (
    PassengerIdentityReconciliationResult,
    reconcile_passenger_identities,
    reconcile_passenger_identities_for_changes,
)
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobilePassengerIdentityModel,
)


@dataclass(frozen=True, slots=True)
class PreparedPassengerChangeIdentities:
    identity_result: PassengerIdentityReconciliationResult | None
    identities: list[tuple[uuid.UUID, uuid.UUID]]


async def prepare_passenger_change_identities(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    passenger_ids: tuple[uuid.UUID, ...],
    actor_user_id: uuid.UUID | None,
    operation: Literal["upsert", "delete"],
    change_kind: MobilePassengerChangeKind,
    reconcile_identities: bool,
) -> PreparedPassengerChangeIdentities:
    identity_result: PassengerIdentityReconciliationResult | None = None
    if reconcile_identities and change_kind == "profile" and access.passenger_access_enabled:
        if 0 < len(passenger_ids) <= _TARGETED_IDENTITY_CHANGE_LIMIT:
            identity_result = await reconcile_passenger_identities_for_changes(
                session,
                access=access,
                actor_user_id=actor_user_id,
                passenger_submission_ids=passenger_ids,
            )
        else:
            identity_result = await reconcile_passenger_identities(
                session,
                access=access,
                actor_user_id=actor_user_id,
            )
    identities: list[tuple[uuid.UUID, uuid.UUID]] = []
    if (
        passenger_ids
        and access.passenger_access_enabled
        and (operation == "upsert" or change_kind == "documents")
    ):
        identity_rows = (
            await session.execute(
                select(
                    MobilePassengerIdentityModel.id,
                    MobilePassengerIdentityModel.passenger_submission_id,
                ).where(
                    MobilePassengerIdentityModel.agency_id == agency_id,
                    MobilePassengerIdentityModel.group_id == group_id,
                    MobilePassengerIdentityModel.gc_group_access_id == access.id,
                    MobilePassengerIdentityModel.passenger_submission_id.in_(passenger_ids),
                    MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
                    MobilePassengerIdentityModel.revoked_at.is_(None),
                )
            )
        ).all()
        identities = [
            (identity_id, passenger_submission_id)
            for identity_id, passenger_submission_id in identity_rows
        ]
    return PreparedPassengerChangeIdentities(identity_result, identities)
