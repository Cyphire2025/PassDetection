"""
Client Submit Passport Use Case
===============================
Finalizes a public client review for an uploaded passport.
"""

from __future__ import annotations

import re
import uuid

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.domain.exceptions.exceptions import EntityNotFoundError, ValidationError
from app.domain.repositories.interfaces import IClientGroupRepository, IPassportSubmissionRepository


class ClientSubmitPassportUseCase:
    """Stores client-reviewed passport data and contact details."""

    def __init__(
        self,
        passport_repo: IPassportSubmissionRepository,
        client_group_repo: IClientGroupRepository,
    ) -> None:
        self._passport_repo = passport_repo
        self._client_group_repo = client_group_repo

    async def execute(
        self,
        submission_id: uuid.UUID,
        *,
        group_token: str,
        confirmed_fields: dict[str, str],
        client_email: str,
        client_phone: str,
    ) -> PassportSubmissionOutputDTO:
        group = await self._client_group_repo.get_by_token(group_token)
        if not group:
            raise EntityNotFoundError("ClientGroup", group_token)

        submission = await self._passport_repo.get_by_id(submission_id)
        if not submission:
            raise EntityNotFoundError("PassportSubmission", submission_id)

        if submission.group_id != group.id:
            raise ValidationError("This passport submission does not belong to this upload link.")

        normalized_email = client_email.lower().strip()
        normalized_phone = self._normalize_phone(client_phone)
        if not normalized_phone:
            raise ValidationError("Enter a valid phone number.", field="client_phone")

        if await self._passport_repo.exists_contact_in_group(
            group.id,
            client_email=normalized_email,
            client_phone=normalized_phone,
            exclude_submission_id=submission.id,
        ):
            raise ValidationError(
                "This email or phone number has already been used for this group.",
                field="client_contact",
            )

        clean_fields = {
            key: value.strip()
            for key, value in confirmed_fields.items()
            if isinstance(value, str) and value.strip()
        }
        if not clean_fields:
            raise ValidationError("At least one reviewed field is required.", field="confirmed_fields")

        submission.submit_client_review(
            clean_fields,
            client_email=normalized_email,
            client_phone=normalized_phone,
        )
        await self._passport_repo.update(submission)

        return PassportSubmissionOutputDTO(
            id=submission.id,
            group_id=submission.group_id,
            agency_id=submission.agency_id,
            client_name=submission.client_name,
            client_email=submission.client_email,
            client_phone=submission.client_phone,
            image_s3_key=submission.image_s3_key,
            thumbnail_s3_key=submission.thumbnail_s3_key,
            status=submission.status.value,
            created_at=submission.created_at,
            updated_at=submission.updated_at,
            extracted_fields=submission.extracted_fields,
            confirmed_fields=submission.confirmed_fields,
            overall_confidence=submission.overall_confidence,
            confidence_score=submission.confidence_score,
            mrz_raw=submission.mrz_raw,
            error_message=submission.error_message,
            client_reviewed_at=submission.client_reviewed_at,
            confirmed_at=submission.confirmed_at,
        )

    def _normalize_phone(self, value: str) -> str:
        normalized = re.sub(r"[^\d+]", "", value.strip())
        if normalized.startswith("+"):
            digits = "+" + re.sub(r"\D", "", normalized[1:])
        else:
            digits = re.sub(r"\D", "", normalized)
        return digits if len(digits.replace("+", "")) >= 7 else ""
