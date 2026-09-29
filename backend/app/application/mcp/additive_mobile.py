"""Preflight the complete mobile plan; permit only new identities and journal rows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.operations import MCPOperationError
from app.application.mobile.passenger_identity_reconciliation import (
    PassengerIdentityPlan,
    _apply_passenger_identity_plan,
    passenger_identity_binding_changed,
    plan_passenger_identities,
)
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobilePassengerIdentityModel,
)
from app.infrastructure.database.models import PassportSubmissionModel


@dataclass(frozen=True, slots=True)
class AdditiveMobilePlan:
    access: GCGroupAccessModel
    plan: PassengerIdentityPlan
    existing: list[MobilePassengerIdentityModel]

    def require_additive(self) -> None:
        desired = {row.passenger_submission_id: row for row in self.plan.candidates}
        for existing in self.existing:
            candidate = desired.get(existing.passenger_submission_id)
            if candidate is None:
                if existing.status != "revoked":
                    raise MCPOperationError("broadcast_link_mobile_change_required")
            elif passenger_identity_binding_changed(existing, candidate):
                raise MCPOperationError("broadcast_link_mobile_change_required")

    async def apply(self, session: AsyncSession, actor_id: uuid.UUID) -> int:
        # Repeat the pure check before using the shared canonical applier. The
        # retained group/access/identity locks remain held through outer commit.
        self.require_additive()
        result = await _apply_passenger_identity_plan(
            session,
            access=self.access,
            actor_user_id=actor_id,
            plan=self.plan,
            existing=self.existing,
        )
        return result.created


async def prepare_additive_mobile_plan(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    submissions: list[PassportSubmissionModel],
    maximum: int = 5000,
) -> AdditiveMobilePlan | None:
    access = await session.scalar(
        select(GCGroupAccessModel)
        .where(
            GCGroupAccessModel.agency_id == agency_id,
            GCGroupAccessModel.group_id == group_id,
            GCGroupAccessModel.is_enabled.is_(True),
            GCGroupAccessModel.passenger_access_enabled.is_(True),
            GCGroupAccessModel.revoked_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if access is None:
        return None
    existing = list(
        (
            await session.scalars(
                select(MobilePassengerIdentityModel)
                .where(
                    MobilePassengerIdentityModel.agency_id == agency_id,
                    MobilePassengerIdentityModel.group_id == group_id,
                    MobilePassengerIdentityModel.gc_group_access_id == access.id,
                )
                .order_by(MobilePassengerIdentityModel.id)
                .limit(maximum + 1)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if len(existing) > maximum or len(submissions) > maximum:
        raise MCPOperationError("broadcast_link_scope_too_large")
    plan = AdditiveMobilePlan(
        access,
        plan_passenger_identities([], submissions, agency_id=agency_id, group_id=group_id),
        existing,
    )
    if (
        len(existing)
        + len(
            {row.passenger_submission_id for row in plan.plan.candidates}
            - {row.passenger_submission_id for row in existing}
        )
        > maximum
    ):
        raise MCPOperationError("broadcast_link_scope_too_large")
    plan.require_additive()
    return plan
