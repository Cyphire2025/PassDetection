"""Serialize AI result publication with company history before locking a source."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel


async def lock_verification_history_scope(session: AsyncSession, submission_id: uuid.UUID) -> None:
    """Two indexed reads at most; preserve group -> company -> source lock order."""
    scope = await session.scalar(select(ClientGroupModel)
        .join(PassportSubmissionModel, (PassportSubmissionModel.group_id == ClientGroupModel.id)
            & (PassportSubmissionModel.agency_id == ClientGroupModel.agency_id))
        .where(PassportSubmissionModel.id == submission_id)
        .execution_options(populate_existing=True)
        .with_for_update(of=ClientGroupModel))
    if scope is not None and scope.company_id is not None:
        await session.scalar(select(ClientOrganizationModel.id).where(
            ClientOrganizationModel.id == scope.company_id,
            ClientOrganizationModel.agency_id == scope.agency_id).with_for_update())
