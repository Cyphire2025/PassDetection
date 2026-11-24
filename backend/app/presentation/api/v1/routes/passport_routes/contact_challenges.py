"""Lock public-upload capabilities and their persisted contact challenges."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.public_upload_capability import require_active_public_upload
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, PassportSubmission
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.public_upload_contact_model import (
    PublicUploadContactChallengeModel,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)

from .public_security import _require_public_upload_credential


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


async def _locked_upload(
    session: AsyncSession, submission_id: uuid.UUID, group_token: str, upload_session_id: str,
) -> PassportSubmission:
    group = await ClientGroupRepository(session).get_by_token(group_token)
    try:
        group = require_active_public_upload(group)
    except EntityNotFoundError as exc:
        raise HTTPException(404, "This upload link is unavailable.") from exc
    submission = await PassportSubmissionRepository(session).get_by_id_for_update(submission_id)
    if submission is None or submission.group_id != group.id:
        raise HTTPException(404, "Passport submission was not found")
    _require_public_upload_credential(submission, upload_session_id)
    if submission.status.value in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES:
        raise HTTPException(409, "Passport details were already submitted.")
    return submission


async def _locked_challenge(
    session: AsyncSession, submission_id: uuid.UUID,
) -> PublicUploadContactChallengeModel | None:
    return (
        await session.execute(
            select(PublicUploadContactChallengeModel)
            .where(PublicUploadContactChallengeModel.submission_id == submission_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
