"""Public passport scope: focused capability and workflow owner."""

from __future__ import annotations

import uuid

from fastapi import (
    HTTPException,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.public_upload_capability import public_upload_is_active
from app.core.logging.logger import get_logger
from app.domain.entities.entities import (
    PassportSubmission,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)

from .public_security import _require_public_upload_credential

logger = get_logger("app.presentation.api.v1.routes.passport_routes.public_upload")


async def _get_public_upload_submission(
    session: AsyncSession,
    *,
    token: str,
    submission_id: uuid.UUID,
    upload_session_id: str,
) -> PassportSubmission:
    group = await ClientGroupRepository(session).get_by_token(token)
    if group is None or not public_upload_is_active(group):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Upload link was not found"
        )
    submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
    if not submission or submission.group_id != group.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passport submission was not found"
        )
    _require_public_upload_credential(submission, upload_session_id)
    return submission


_get_public_upload_submission.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.public_upload"
)
