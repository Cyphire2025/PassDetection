"""Transactional roster refresh for changes to an existing linked broadcast.

Admission reads at most 101 links and locks at most 100 groups, then companies,
then durable jobs, before the caller locks its broadcast/recipients. The caller
revalidates the link set after that lock. No identities or history are read.
Memory is O(min(linked groups, 101)); job admission is O(linked groups) indexed
queries, capped at 100. Worker matching retains its existing 25-row pages.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.incremental_history import coalesce_job, refresh_job
from app.domain.exceptions.exceptions import ConflictError
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerReconciliationJobModel,
    TravellerReusePolicyModel,
)

MAX_BROADCAST_REFRESH_GROUPS = 100


@dataclass(frozen=True, slots=True)
class BroadcastHistoryRefresh:
    agency_id: uuid.UUID
    broadcast_id: uuid.UUID
    group_ids: tuple[uuid.UUID, ...]
    jobs: tuple[TravellerReconciliationJobModel, ...]


def _links(agency_id: uuid.UUID, broadcast_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    return select(ClientGroupWhatsAppBroadcastLinkModel.client_group_id).where(
        ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
        ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == broadcast_id)


async def prepare_broadcast_history_refresh(session: AsyncSession, *, agency_id: uuid.UUID,
    broadcast_id: uuid.UUID,
) -> BroadcastHistoryRefresh:
    """Call before any broadcast/recipient lock; rollback owns failure cleanup."""
    group_ids = tuple(await session.scalars(_links(agency_id, broadcast_id)
        .order_by(ClientGroupWhatsAppBroadcastLinkModel.client_group_id).limit(MAX_BROADCAST_REFRESH_GROUPS + 1)))
    if len(group_ids) > MAX_BROADCAST_REFRESH_GROUPS:
        raise ConflictError("This broadcast is linked to more than 100 groups. Reduce its group links before changing contacts.")
    rows = (await session.execute(select(ClientGroupModel.id, ClientGroupModel.company_id,
        ClientGroupModel.company_revision, ClientGroupModel.status, ClientGroupModel.deleted_at, ClientGroupModel.import_only)
        .where(ClientGroupModel.agency_id == agency_id, ClientGroupModel.id.in_(group_ids))
        # NO KEY UPDATE serializes edits while allowing workers' FK key-share
        # inserts for other groups. FOR UPDATE can deadlock multi-group admission.
        .order_by(ClientGroupModel.id).with_for_update(of=ClientGroupModel, key_share=True))).all() if group_ids else []
    company_ids = sorted({row.company_id for row in rows if row.company_id is not None
        and row.status == "active" and row.deleted_at is None}, key=str)
    active_companies = set(await session.scalars(select(ClientOrganizationModel.id).where(
        ClientOrganizationModel.agency_id == agency_id, ClientOrganizationModel.id.in_(company_ids),
        ClientOrganizationModel.status == "active").order_by(ClientOrganizationModel.id)
        .with_for_update(key_share=True))) if company_ids else set()
    policies = {policy.company_id: policy.revision for policy in await session.scalars(
        select(TravellerReusePolicyModel).where(TravellerReusePolicyModel.agency_id == agency_id,
            TravellerReusePolicyModel.company_id.in_(active_companies), TravellerReusePolicyModel.enabled.is_(True)))} if active_companies else {}
    now = datetime.now(UTC)
    jobs = []
    for row in rows:
        revision = policies.get(row.company_id)
        if revision is not None and row.status == "active" and row.deleted_at is None and not row.import_only:
            jobs.append(await coalesce_job(session, agency_id=agency_id, company_id=row.company_id,
                group_id=row.id, group_revision=row.company_revision,
                key=f"company-roster:m:{revision}:{row.company_revision}", now=now))
    return BroadcastHistoryRefresh(agency_id, broadcast_id, group_ids, tuple(jobs))


async def require_current_broadcast_history_scope(session: AsyncSession, prepared: BroadcastHistoryRefresh) -> None:
    """Caller now holds the broadcast lock. Any changed link rolls everything back."""
    current = tuple(await session.scalars(_links(prepared.agency_id, prepared.broadcast_id)
        .order_by(ClientGroupWhatsAppBroadcastLinkModel.client_group_id).limit(MAX_BROADCAST_REFRESH_GROUPS + 1)))
    if current != prepared.group_ids:
        raise ConflictError("The linked groups changed. Refresh the broadcast and try again.")


async def finish_broadcast_history_refresh(session: AsyncSession, prepared: BroadcastHistoryRefresh) -> None:
    """Advance the source cutoff after contact writes; never commit separately."""
    await session.flush()
    now = datetime.now(UTC)
    for job in prepared.jobs:
        refresh_job(job, group_revision=job.expected_group_revision, now=now)
    await session.flush()
