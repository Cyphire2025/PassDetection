"""Single assignment transaction used by group editing and GC App.

Point lookups and dependency EXISTS probes use tenant/key indexes: O(log N)
lookup work and O(1) application memory, without loading a passenger roster.
Callers own commit/rollback; a company row lock serializes deactivate/delete
against assignment and creation. No lifecycle, retention or messaging changes.
"""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.data_exports import invalidate_company_exports
from app.application.companies.reassignment import (
    ReassignmentReview,
    require_reassignment_review,
    stage_reassignment,
)
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import ConflictError, EntityNotFoundError, ValidationError
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientOrganizationModel,
    GCGroupAccessModel,
)
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerParticipationModel,
    TravellerReconciliationJobModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


async def require_active_company(
    session: AsyncSession, agency_id: uuid.UUID, company_id: uuid.UUID,
) -> ClientOrganizationModel:
    company = await session.scalar(
        select(ClientOrganizationModel).where(
            ClientOrganizationModel.id == company_id,
            ClientOrganizationModel.agency_id == agency_id,
            ClientOrganizationModel.status == "active",
        ).with_for_update().execution_options(populate_existing=True)
    )
    if company is None:
        raise ValidationError("Select an active company/client in this agency", field="company_id")
    return company


async def assign_group_company(
    session: AsyncSession, *, user: User, agency_id: uuid.UUID, group_id: uuid.UUID,
    company_id: uuid.UUID, expected_revision: int | None,
    review: ReassignmentReview | None = None,
) -> ClientGroupModel:
    # Lock group first consistently with existing GC App and ingestion paths.
    group = await session.scalar(
        select(ClientGroupModel).where(
            ClientGroupModel.id == group_id, ClientGroupModel.agency_id == agency_id,
        ).with_for_update(of=ClientGroupModel).execution_options(populate_existing=True)
    )
    if group is None:
        raise EntityNotFoundError("ClientGroup", group_id)
    await AuthorizationPolicy(session).require_manage_group(user, group)
    if group.status == "deleted":
        raise ConflictError("Deleted groups cannot be assigned to a company")
    if expected_revision is None or expected_revision != group.company_revision:
        raise ConflictError("Company assignment changed; refresh and retry")
    if group.company_id == company_id:
        return group  # Retain an older inactive selection without reassigning it.
    company = await require_active_company(session, agency_id, company_id)
    previous_id = group.company_id
    access = await session.scalar(select(GCGroupAccessModel).where(
        GCGroupAccessModel.agency_id == agency_id, GCGroupAccessModel.group_id == group_id,
    ).with_for_update().execution_options(populate_existing=True))
    if access is not None and access.client_organization_id != company_id:
        conflict = await session.scalar(select(ClientManagerGroupAssignmentModel.id).where(
            ClientManagerGroupAssignmentModel.agency_id == agency_id,
            ClientManagerGroupAssignmentModel.group_id == group_id,
            ClientManagerGroupAssignmentModel.is_active.is_(True),
        ).limit(1))
        if conflict:
            raise ConflictError("Remove Client Manager assignments before changing the company")
    if review is not None:
        require_reassignment_review(user, group, review)
    if previous_id is not None and review is None:
        populated = await session.scalar(select(or_(
            select(PassportSubmissionModel.id).where(PassportSubmissionModel.agency_id == agency_id,
                                                     PassportSubmissionModel.group_id == group_id).exists(),
            select(TravellerParticipationModel.id).where(TravellerParticipationModel.agency_id == agency_id,
                                                          TravellerParticipationModel.group_id == group_id).exists(),
            select(TravellerReconciliationJobModel.id).where(TravellerReconciliationJobModel.agency_id == agency_id,
                                                              TravellerReconciliationJobModel.group_id == group_id).exists(),
        )))
        if populated:
            raise ConflictError("Populated group reassignment requires a company administrator impact preview and reconciliation")
    group.company_id = company.id
    group.company_revision += 1
    if access is not None:
        access.client_organization_id = company.id
        access.revision += 1
        access.access_generation += 1
    if previous_id is not None:
        await stage_reassignment(session, group=group, previous_company_id=previous_id)
        await invalidate_company_exports(session, agency_id, previous_id)
    from app.application.travellers.history_schedule import schedule_group_history
    await schedule_group_history(session, group=group, trigger=f"assignment:{group.id}:{group.company_revision}")
    await session.flush()
    await AuditLogRepository(session).record(
        action="company.group_assigned" if previous_id is None else "company.group_reassigned",
        entity_type="client_group", entity_id=str(group.id), agency_id=agency_id,
        user_id=user.id, actor_email=user.email,
        metadata={"previous_company_id": str(previous_id) if previous_id else None,
                  "company_id": str(company.id), "revision": group.company_revision,
                  "reason": review.reason if review else None,
                  "expected_roster_revision": review.expected_roster_revision if review else None},
    )
    await session.refresh(group, attribute_names=["company"])
    return group
