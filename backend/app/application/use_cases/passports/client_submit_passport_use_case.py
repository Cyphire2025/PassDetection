"""
Client Submit Passport Use Case
===============================
Finalizes a public client review for an uploaded passport.
"""

from __future__ import annotations

import re
import uuid
from pathlib import PurePosixPath

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.domain.exceptions.exceptions import EntityNotFoundError, ValidationError
from app.domain.repositories.interfaces import IClientGroupRepository, IObjectStorageRepository, IPassportSubmissionRepository


class ClientSubmitPassportUseCase:
    """Stores client-reviewed passport data and contact details."""

    def __init__(
        self,
        passport_repo: IPassportSubmissionRepository,
        client_group_repo: IClientGroupRepository,
        storage_repo: IObjectStorageRepository,
    ) -> None:
        self._passport_repo = passport_repo
        self._client_group_repo = client_group_repo
        self._storage_repo = storage_repo

    async def execute(
        self,
        submission_id: uuid.UUID,
        *,
        group_token: str,
        confirmed_fields: dict[str, str],
        client_email: str | None,
        client_phone: str | None,
        departure_city: str | None = None,
        submission_mode: str = "single",
        family_group_id: uuid.UUID | None = None,
        family_member_index: int | None = None,
        family_relation: str | None = None,
        family_gender: str | None = None,
        family_head_name: str | None = None,
        family_head_email: str | None = None,
        family_head_phone: str | None = None,
    ) -> PassportSubmissionOutputDTO:
        group = await self._client_group_repo.get_by_token(group_token)
        if not group:
            raise EntityNotFoundError("ClientGroup", group_token)

        submission = await self._passport_repo.get_by_id(submission_id)
        if not submission:
            raise EntityNotFoundError("PassportSubmission", submission_id)

        if submission.group_id != group.id:
            raise ValidationError("This passport submission does not belong to this upload link.")

        normalized_mode = "family" if submission_mode == "family" else "single"
        normalized_email = client_email.lower().strip() if client_email and client_email.strip() else None
        normalized_phone = self._normalize_phone(client_phone) if client_phone and client_phone.strip() else None
        normalized_head_email = family_head_email.lower().strip() if family_head_email and family_head_email.strip() else None
        normalized_head_phone = self._normalize_phone(family_head_phone) if family_head_phone and family_head_phone.strip() else None

        if normalized_mode == "single":
            if not normalized_email:
                raise ValidationError("Enter a valid email address.", field="client_email")
            if not normalized_phone:
                raise ValidationError("Enter a valid phone number.", field="client_phone")
            normalized_head_name = None
            normalized_head_email = None
            normalized_head_phone = None
            family_group_id = None
            family_member_index = None
            normalized_relation = None
            normalized_gender = None
        else:
            if not family_group_id:
                raise ValidationError("Family group id is required.", field="family_group_id")
            normalized_head_name = " ".join((family_head_name or "").strip().split())
            if len(normalized_head_name) < 2:
                raise ValidationError("Head of family name is required.", field="family_head_name")
            if not normalized_head_email:
                raise ValidationError("Head of family email is required.", field="family_head_email")
            if not normalized_head_phone:
                raise ValidationError("Head of family phone number is required.", field="family_head_phone")
            if client_phone and not normalized_phone:
                raise ValidationError("Enter a valid family member phone number.", field="client_phone")
            normalized_relation = " ".join((family_relation or "").strip().split())[:80] or None
            normalized_gender = " ".join((family_gender or "").strip().split())[:40] or None

        normalized_departure_city = self._normalize_departure_city(departure_city, group.departure_cities)

        if normalized_mode == "single" and (normalized_email or normalized_phone) and await self._passport_repo.exists_contact_in_group(
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

        draft_key = submission.image_s3_key
        if draft_key.startswith("drafts/"):
            suffix = PurePosixPath(draft_key).suffix or ".jpg"
            permanent_key = f"{submission.agency_id}/{submission.group_id}/{submission.id}{suffix}"
            image = await self._storage_repo.get_file(draft_key)
            await self._storage_repo.upload_file(image, permanent_key, self._content_type(suffix))
            submission.promote_image(permanent_key)

        submission.submit_client_review(
            clean_fields,
            client_email=normalized_email,
            client_phone=normalized_phone,
            departure_city=normalized_departure_city,
            submission_mode=normalized_mode,
            family_group_id=family_group_id,
            family_member_index=family_member_index,
            family_relation=normalized_relation,
            family_gender=normalized_gender,
            family_head_name=normalized_head_name,
            family_head_email=normalized_head_email,
            family_head_phone=normalized_head_phone,
            family_broadcast_to_member=bool(normalized_email or normalized_phone),
        )
        await self._passport_repo.update(submission)
        if draft_key != submission.image_s3_key:
            await self._storage_repo.delete_files([draft_key])

        return PassportSubmissionOutputDTO(
            id=submission.id,
            group_id=submission.group_id,
            agency_id=submission.agency_id,
            client_name=submission.client_name,
            client_email=submission.client_email,
            client_phone=submission.client_phone,
            departure_city=submission.departure_city,
            submission_mode=submission.submission_mode,
            family_group_id=submission.family_group_id,
            family_member_index=submission.family_member_index,
            family_relation=submission.family_relation,
            family_gender=submission.family_gender,
            family_head_name=submission.family_head_name,
            family_head_email=submission.family_head_email,
            family_head_phone=submission.family_head_phone,
            family_broadcast_to_member=submission.family_broadcast_to_member,
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

    def _normalize_phone(self, value: str | None) -> str:
        if not value:
            return ""
        normalized = re.sub(r"[^\d+]", "", value.strip())
        if normalized.startswith("+"):
            digits = "+" + re.sub(r"\D", "", normalized[1:])
        else:
            digits = re.sub(r"\D", "", normalized)
        return digits if len(digits.replace("+", "")) >= 7 else ""

    @staticmethod
    def _normalize_departure_city(value: str | None, allowed_cities: list[str]) -> str | None:
        cities = [" ".join(city.strip().split()) for city in allowed_cities if city and city.strip()]
        if not cities:
            return " ".join(value.strip().split())[:120] if value and value.strip() else None
        selected = " ".join(value.strip().split()) if value else ""
        if not selected:
            raise ValidationError("Select your departure city.", field="departure_city")
        city_by_key = {city.casefold(): city for city in cities}
        matched = city_by_key.get(selected.casefold())
        if not matched:
            raise ValidationError("Select a valid departure city for this group.", field="departure_city")
        return matched

    @staticmethod
    def _content_type(suffix: str) -> str:
        return "image/png" if suffix.lower() == ".png" else "image/jpeg"
