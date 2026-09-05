"""Recover a durable public upload from its browser-held attempt identifier."""

from __future__ import annotations

import uuid

from app.application.security.public_upload_capability import public_upload_is_active
from app.core.security.upload_session import is_valid_upload_credential
from app.domain.repositories.interfaces import (
    IClientGroupRepository,
    IPassportSubmissionRepository,
)


class ReconcilePassportUploadUseCase:
    """Resolve an upload attempt only inside its active bearer-link scope."""

    def __init__(
        self,
        client_group_repo: IClientGroupRepository,
        passport_repo: IPassportSubmissionRepository,
    ) -> None:
        self._client_group_repo = client_group_repo
        self._passport_repo = passport_repo

    async def execute(
        self,
        *,
        token: str,
        upload_idempotency_key: str,
    ) -> uuid.UUID | None:
        # Presentation validation normally rejects malformed identifiers. Keep
        # this boundary safe for non-HTTP callers without normalizing the key:
        # the exact opaque value is what was committed with the submission.
        if not is_valid_upload_credential(upload_idempotency_key):
            return None

        group = await self._client_group_repo.get_by_token(token)
        if group is None or not public_upload_is_active(group):
            return None

        submission = await self._passport_repo.get_by_upload_idempotency_key(
            group.id,
            upload_idempotency_key,
        )
        return submission.id if submission is not None else None
