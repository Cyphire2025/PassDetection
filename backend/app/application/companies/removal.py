"""Remove a client directory entry while preserving every source/history row.

Administrative removal is bounded to 500 groups and 5,000 manager grants per
transaction. Queries use scoped keys; app memory is O(group_limit). Larger
clients are rejected before any writes instead of monopolizing an HTTP worker.
The caller locks the company first; NOWAIT group/grant locks prevent an inverted
assignment lock order from deadlocking. Every change and audit is one transaction.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import case, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import ConflictError
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientOrganizationModel,
    GCGroupAccessModel,
)
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_reuse_models import TravellerReconciliationJobModel

MAX_REMOVAL_GROUPS = 500
MAX_REMOVAL_MANAGER_GRANTS = 5_000
MAX_REMOVAL_JOBS = 5_000


async def detach_company_groups(session: AsyncSession, *, company: ClientOrganizationModel, user: User) -> dict[str, int]:
    group, grant, access = ClientGroupModel, ClientManagerGroupAssignmentModel, GCGroupAccessModel
    job = TravellerReconciliationJobModel
    try:
        group_ids = list(await session.scalars(select(group.id).where(
            group.agency_id == company.agency_id, group.company_id == company.id,
        ).order_by(group.id).limit(MAX_REMOVAL_GROUPS + 1).with_for_update(nowait=True)))
        if len(group_ids) > MAX_REMOVAL_GROUPS:
            raise ConflictError("This client has too many groups for one removal. Contact support to schedule its removal.")
        grant_ids = list(await session.scalars(select(grant.id).where(
            grant.agency_id == company.agency_id, grant.organization_id == company.id,
        ).order_by(grant.id).limit(MAX_REMOVAL_MANAGER_GRANTS + 1).with_for_update(nowait=True)))
        if len(grant_ids) > MAX_REMOVAL_MANAGER_GRANTS:
            raise ConflictError("This client has too many manager assignments for one removal. Contact support to schedule its removal.")
        # Lock accesses before changing any references; these have the same group
        # scope and at most one row per group. A concurrent publisher retries.
        list(await session.scalars(select(access.id).where(access.agency_id == company.agency_id,
            access.client_organization_id == company.id).limit(MAX_REMOVAL_GROUPS + 1).with_for_update(nowait=True)))
        job_ids = list(await session.scalars(select(job.id).where(job.agency_id == company.agency_id,
            job.company_id == company.id, job.status.in_(("queued", "running", "failed")))
            .order_by(job.id).limit(MAX_REMOVAL_JOBS + 1).with_for_update(nowait=True)))
        if len(job_ids) > MAX_REMOVAL_JOBS:
            raise ConflictError("This client's background work needs to finish before removal. Retry later.")
    except DBAPIError as exc:
        if (getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)) == "55P03":
            raise ConflictError("A linked group is being updated. Retry the company removal in a moment.") from exc
        raise
    now = datetime.now(UTC)
    if grant_ids:
        # Keep manager profiles and grant history. Only company-specific access
        # is revoked when its company association ceases to exist.
        await session.execute(update(grant).where(grant.id.in_(grant_ids), grant.agency_id == company.agency_id).values(
            organization_id=None, is_active=False, revoked_at=func.coalesce(grant.revoked_at, now),
            revoked_by_user_id=case((grant.is_active.is_(True), user.id), else_=grant.revoked_by_user_id),
        ))
    await session.execute(update(access).where(access.agency_id == company.agency_id,
        access.client_organization_id == company.id).values(client_organization_id=None,
        client_manager_access_enabled=False, revision=access.revision + 1, access_generation=access.access_generation + 1))
    if group_ids:
        await session.execute(update(group).where(group.id.in_(group_ids), group.agency_id == company.agency_id,
            group.company_id == company.id).values(company_id=None, company_revision=group.company_revision + 1))
    if job_ids:
        await session.execute(update(job).where(job.agency_id == company.agency_id, job.id.in_(job_ids))
            .values(status="cancelled", lease_expires_at=None, last_error_code="company_removed"))
    return {"detached_groups": len(group_ids), "retained_manager_grants": len(grant_ids)}
