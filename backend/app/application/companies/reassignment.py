"""Review evidence and durable context transition for populated reassignment.

Preview counts use indexed aggregates and O(1) application memory. The request
never copies profiles or scans passport contents. Reconciliation is a durable
keyset job, fenced by the new group revision. Frozen participation and document
references retain their original company provenance.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import ScalarSelect

from app.application.companies.access import COMPANY_ADMIN_ROLES, require_company
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError, ConflictError, EntityNotFoundError
from app.infrastructure.database.gc_mobile_models import ClientManagerGroupAssignmentModel
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerClaimModel,
    TravellerHistoryGrantModel,
    TravellerParticipationModel,
    TravellerReconciliationJobModel,
)


@dataclass(frozen=True)
class ReassignmentReview:
    expected_roster_revision: int
    reason: str


def require_reassignment_review(user: User, group: ClientGroupModel, review: ReassignmentReview) -> None:
    if user.role not in COMPANY_ADMIN_ROLES:
        raise AuthorizationError("Company administration permission is required for this reassignment")
    if group.roster_revision != review.expected_roster_revision:
        raise ConflictError("Group records changed after the impact preview; refresh and review again")
    if not 10 <= len(review.reason.strip()) <= 500:
        raise ConflictError("Provide a reassignment reason between 10 and 500 characters")


async def reassignment_preview(
    session: AsyncSession, *, user: User, agency_id: uuid.UUID, group_id: uuid.UUID, company_id: uuid.UUID,
) -> dict[str, object]:
    target = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    group = await session.scalar(select(ClientGroupModel).where(
        ClientGroupModel.id == group_id, ClientGroupModel.agency_id == agency_id,
    ))
    if group is None:
        raise EntityNotFoundError("ClientGroup", group_id)
    await AuthorizationPolicy(session).require_manage_group(user, group)
    now = datetime.now(UTC)

    def count(
        model: type[PassportSubmissionModel] | type[TravellerParticipationModel] | type[TravellerClaimModel]
            | type[TravellerHistoryGrantModel] | type[ClientManagerGroupAssignmentModel],
        *filters: ColumnElement[bool],
    ) -> ScalarSelect[int]:
        return select(func.count()).select_from(model).where(
            model.agency_id == agency_id, model.group_id == group_id, *filters,
        ).scalar_subquery()

    counts = (await session.execute(select(
        count(PassportSubmissionModel).label("submission_records"),
        count(TravellerParticipationModel, TravellerParticipationModel.status == "accepted").label("accepted_participations"),
        count(TravellerClaimModel, TravellerClaimModel.revoked_at.is_(None), TravellerClaimModel.expires_at > now,
              TravellerClaimModel.status.notin_(("consumed", "revoked", "locked"))).label("active_claims"),
        count(TravellerHistoryGrantModel, TravellerHistoryGrantModel.revoked_at.is_(None),
              TravellerHistoryGrantModel.absolute_expires_at > now,
              TravellerHistoryGrantModel.inactivity_expires_at > now).label("active_grants"),
        count(ClientManagerGroupAssignmentModel, ClientManagerGroupAssignmentModel.is_active.is_(True)).label("managers"),
    ))).mappings().one()
    return {
        "group_id": group.id, "source_company_id": group.company_id, "target_company_id": target.id,
        "expected_revision": group.company_revision, "expected_roster_revision": group.roster_revision,
        **{key: counts[key] for key in ("submission_records", "accepted_participations", "active_claims", "active_grants")},
        "manager_conflict": bool(counts["managers"]),
        "can_reassign": target.status == "active" and group.status != "deleted" and not counts["managers"],
    }


async def stage_reassignment(
    session: AsyncSession, *, group: ClientGroupModel, previous_company_id: uuid.UUID,
) -> None:
    assert group.company_id is not None, "Reassignment requires an assigned target company"
    now = datetime.now(UTC)
    # Version fencing on every retrieval is authoritative, including expired
    # historical rows. Persist revocation of only currently live public access.
    await session.execute(update(TravellerClaimModel).where(
        TravellerClaimModel.agency_id == group.agency_id, TravellerClaimModel.group_id == group.id,
        TravellerClaimModel.company_id == previous_company_id, TravellerClaimModel.revoked_at.is_(None),
        TravellerClaimModel.expires_at > now, TravellerClaimModel.status.notin_(("consumed", "revoked", "locked")),
    ).values(status="revoked", revoked_at=now).execution_options(synchronize_session="fetch"))
    await session.execute(update(TravellerHistoryGrantModel).where(
        TravellerHistoryGrantModel.agency_id == group.agency_id, TravellerHistoryGrantModel.group_id == group.id,
        TravellerHistoryGrantModel.company_id == previous_company_id, TravellerHistoryGrantModel.revoked_at.is_(None),
        TravellerHistoryGrantModel.absolute_expires_at > now,
    ).values(revoked_at=now).execution_options(synchronize_session="fetch"))
    await session.execute(update(TravellerReconciliationJobModel).where(
        TravellerReconciliationJobModel.agency_id == group.agency_id,
        TravellerReconciliationJobModel.group_id == group.id,
        TravellerReconciliationJobModel.status.in_(("queued", "running")),
    ).values(status="cancelled", completed_at=now, last_error_code="company_reassigned").execution_options(synchronize_session="fetch"))
    from app.application.travellers.reconciliation import enqueue_reconciliation
    await enqueue_reconciliation(
        session, agency_id=group.agency_id, company_id=group.company_id, group_id=group.id,
        idempotency_key=f"company-reassignment:{group.company_revision}", now=now,
    )
