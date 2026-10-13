"""Small transactional source hooks; durable workers perform historical work."""

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.data_exports import invalidate_company_exports
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerReconciliationJobModel,
    TravellerReusePolicyModel,
)


async def schedule_group_history(session: AsyncSession, *, group: ClientGroupModel, trigger: str) -> None:
    """Caller holds group lock. Enqueue one idempotent job, never load a roster."""
    if group.company_id is None or group.deleted_at is not None or group.status == "deleted":
        return
    policy = await session.scalar(select(TravellerReusePolicyModel).where(
        TravellerReusePolicyModel.company_id == group.company_id,
        TravellerReusePolicyModel.agency_id == group.agency_id,
        TravellerReusePolicyModel.enabled.is_(True)))
    await session.scalar(select(ClientOrganizationModel.id).where(
        ClientOrganizationModel.id == group.company_id, ClientOrganizationModel.agency_id == group.agency_id).with_for_update())
    await invalidate_company_exports(session, group.agency_id, group.company_id)
    from app.application.travellers.incremental_history import queue_group_refresh
    await queue_group_refresh(session, group, policy, datetime.now(UTC))


async def schedule_company_history_initialization(session: AsyncSession, *, company: ClientOrganizationModel) -> None:
    """Bounded lazy initial admission; caller authorizes the staff directory."""
    eligible = (
        ClientGroupModel.agency_id == company.agency_id, ClientGroupModel.company_id == company.id,
        ClientGroupModel.deleted_at.is_(None), ClientGroupModel.status.in_(("active", "closed", "archived")))
    trigger = f"private-initial:{company.id}"
    key = "company-history:p:0:" + hashlib.sha256(trigger.encode()).hexdigest()[:24]
    first_id = select(ClientGroupModel.id).where(*eligible).order_by(ClientGroupModel.id).limit(1).scalar_subquery()
    existing = await session.scalar(select(TravellerReconciliationJobModel.id).where(
        TravellerReconciliationJobModel.agency_id == company.agency_id,
        TravellerReconciliationJobModel.company_id == company.id,
        TravellerReconciliationJobModel.group_id == first_id,
        TravellerReconciliationJobModel.idempotency_key == key).limit(1))
    if existing is not None:
        return  # Established readers never acquire an exclusive group lock.
    first = await session.scalar(select(ClientGroupModel).where(*eligible)
        .order_by(ClientGroupModel.id).limit(1).with_for_update())
    if first is not None:
        from app.application.travellers.company_history_jobs import enqueue_private_company_history
        await enqueue_private_company_history(session, group=first, trigger=trigger)


async def schedule_submission_history(session: AsyncSession, *, agency_id: uuid.UUID,
    group_id: uuid.UUID, trigger: str, source_submission_id: uuid.UUID | None = None,
    expected_extraction_revision: int | None = None,
) -> None:
    """Use only after the source flow's existing group lock, before its commit."""
    group = await session.scalar(select(ClientGroupModel).where(
        ClientGroupModel.id == group_id, ClientGroupModel.agency_id == agency_id))
    if group is None or group.company_id is None or group.deleted_at is not None or group.status == "deleted":
        return
    if source_submission_id is None or expected_extraction_revision is None:
        await schedule_group_history(session, group=group, trigger=trigger)
        return
    await session.scalar(select(ClientOrganizationModel.id).where(
        ClientOrganizationModel.id == group.company_id, ClientOrganizationModel.agency_id == group.agency_id).with_for_update())
    await invalidate_company_exports(session, agency_id, group.company_id)
    from app.application.travellers.incremental_history import coalesce_job
    await coalesce_job(session, agency_id=agency_id, company_id=group.company_id, group_id=group.id,
        group_revision=group.company_revision,
        key=f"company-source:{source_submission_id}:{expected_extraction_revision}", now=datetime.now(UTC))
