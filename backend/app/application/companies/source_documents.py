"""Every resolved historical source remains addressable, including incomplete IDs."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import visible_company_groups
from app.application.travellers.snapshot_access import can_read_snapshot_asset
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, User
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.models import PassportSubmissionModel as Submission
from app.infrastructure.database.traveller_reuse_models import TravellerMatchCaseModel as MatchCase
from app.infrastructure.database.traveller_reuse_models import (
    TravellerReconciliationJobModel as Job,
)

SOURCE_SIDES = {"front": "image_s3_key", "back": "passport_back_s3_key", "cover": "passport_cover_s3_key",
    "back_cover": "passport_back_cover_s3_key", "photo": "passport_photo_s3_key"}


async def require_source(session: AsyncSession, *, user: User, agency_id: uuid.UUID,
    company_id: uuid.UUID, person_id: uuid.UUID, source_id: uuid.UUID,
) -> Submission:
    groups = visible_company_groups(user, agency_id, company_id).with_only_columns(ClientGroupModel.id)
    associated = select(MatchCase.id).where(MatchCase.agency_id == agency_id,
        MatchCase.company_id == company_id, MatchCase.traveller_id == person_id,
        MatchCase.source_kind == "passport_submission", MatchCase.source_row_key == str(source_id),
        MatchCase.status == "resolved", MatchCase.group_id == Submission.group_id).exists()
    source = await session.scalar(select(Submission).where(Submission.id == source_id,
        Submission.agency_id == agency_id, Submission.group_id.in_(groups), associated,
        Submission.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES)))
    if source is None:
        raise EntityNotFoundError("Source document", source_id)
    return source


async def source_document_key(session: AsyncSession, source: Submission, side: str) -> str:
    key = getattr(source, SOURCE_SIDES.get(side, ""), None)
    if not isinstance(key, str) or not key or not await can_read_snapshot_asset(session,
        submission_id=source.id, group_id=source.group_id, agency_id=source.agency_id, storage_key=key):
        raise EntityNotFoundError("Source document", source.id)
    return key


async def indexing_pending(session: AsyncSession, agency_id: uuid.UUID, company_id: uuid.UUID) -> bool:
    return bool(await session.scalar(select(select(Job.id).where(Job.agency_id == agency_id,
        Job.company_id == company_id, or_(Job.status.in_(("queued", "running")),
            (Job.status == "succeeded") & (Job.last_error_code == "chain_advance_pending"))).exists())))
