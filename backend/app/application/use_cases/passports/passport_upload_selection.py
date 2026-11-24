"""Validate the durable qualifier selection and its matching replay credential."""

from __future__ import annotations

import uuid

from app.domain.entities.entities import PassportSubmission, QualifierSelection
from app.domain.exceptions.exceptions import ValidationError
from app.domain.repositories.interfaces import (
    IPassportSubmissionRepository,
    IQualifierSelectionRepository,
)
from app.domain.value_objects.qualifier_relations import hash_qualifier_selection_token


async def require_qualifier_selection(
    *,
    group_id: uuid.UUID,
    selection_token: str | None,
    upload_idempotency_key: str | None,
    selection_repo: IQualifierSelectionRepository | None,
    passport_repo: IPassportSubmissionRepository,
) -> tuple[QualifierSelection, PassportSubmission | None]:
    if not selection_token:
        raise ValidationError(
            "Select Self or the passenger's relationship before uploading.",
            field="qualifier_selection_token",
        )
    if selection_repo is None:
        raise ValidationError(
            "The qualifier selection could not be verified.",
            field="qualifier_selection_token",
        )
    selection = await selection_repo.get_by_token_hash(
        group_id,
        hash_qualifier_selection_token(selection_token),
        for_update=True,
    )
    if selection is None:
        raise ValidationError(
            "The qualifier selection is invalid.",
            field="qualifier_selection_token",
        )
    if selection.group_id != group_id:
        raise ValidationError(
            "The qualifier selection does not belong to this upload link.",
            field="qualifier_selection_token",
        )
    associated_submission_id = await selection_repo.get_submission_id(selection.id)
    if associated_submission_id is not None:
        associated = await passport_repo.get_by_id(associated_submission_id)
        if (
            associated is not None
            and associated.group_id == group_id
            and upload_idempotency_key
            and associated.upload_idempotency_key == upload_idempotency_key
        ):
            return selection, associated
        raise ValidationError(
            "This qualifier selection has already been used.",
            field="qualifier_selection_token",
        )
    if selection.is_expired():
        raise ValidationError(
            "This qualifier selection has expired. Please choose again.",
            field="qualifier_selection_token",
        )
    return selection, None
