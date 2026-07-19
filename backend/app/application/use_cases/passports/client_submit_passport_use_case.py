"""
Client Submit Passport Use Case
===============================
Finalizes a public client review for an uploaded passport.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import replace
from pathlib import PurePosixPath

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.core.logging.logger import get_logger
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.domain.exceptions.exceptions import EntityNotFoundError, ValidationError
from app.domain.repositories.interfaces import (
    IClientGroupRepository,
    IObjectStorageRepository,
    IPassportSubmissionRepository,
)
from app.domain.value_objects.passport_document_classification import (
    is_accepted_passport_information_page,
    passport_document_classification,
)
from app.domain.value_objects.passport_fields import (
    normalize_reviewed_passport_fields,
    validate_reviewed_passport_payload,
)

logger = get_logger(__name__)

PUBLIC_DOCUMENT_CLASSIFICATION_REQUIRED = (
    "We could not confirm that this is a passport photo and details page. "
    "Retry automatic reading or replace the saved passport pages before submitting."
)


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
        nearest_domestic_airport: str | None = None,
        base_city: str | None = None,
        staff_code: str | None = None,
        meal_preference: str | None = None,
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

        submission = await self._passport_repo.get_by_id_for_update(submission_id)
        if not submission:
            raise EntityNotFoundError("PassportSubmission", submission_id)

        if submission.group_id != group.id:
            raise ValidationError("This passport submission does not belong to this upload link.")
        if not submission.image_s3_key or submission.image_s3_key.startswith("excel-imports/"):
            raise ValidationError("Passport front image is required.", field="file")
        if not submission.passport_back_s3_key:
            raise ValidationError("Passport back image is required.", field="passport_back_file")
        if group.require_selfie and not submission.passport_photo_s3_key:
            raise ValidationError(
                "Visa Photo is required for this upload link.",
                field="passport_photo_file",
            )
        if (
            submission.status.value not in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
            and not is_accepted_passport_information_page(
                passport_document_classification(submission.extracted_fields)
            )
        ):
            # The browser cannot bypass the final server-side document gate by
            # manually entering plausible passport fields. This also fails
            # closed while Gemini classification is unavailable or incomplete.
            raise ValidationError(
                PUBLIC_DOCUMENT_CLASSIFICATION_REQUIRED,
                field="file",
            )
        normalized_mode = "family" if submission_mode == "family" else "single"
        if submission.qualifier_enabled_snapshot and normalized_mode != "single":
            raise ValidationError(
                "Relation with Qualifier uploads support one passenger only.",
                field="submission_mode",
            )
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

        airport_enabled = group.nearest_international_airport_enabled or bool(group.departure_cities)
        normalized_departure_city = self._normalize_departure_city(
            departure_city,
            group.departure_cities,
            enabled=airport_enabled,
        )
        normalized_base_city = self._normalize_configured_text(
            base_city,
            enabled=group.base_city_enabled,
            field="base_city",
            label="base city",
            max_length=120,
        )
        normalized_domestic_airport = self._normalize_configured_text(
            nearest_domestic_airport,
            enabled=group.ask_nearest_domestic_airport,
            field="nearest_domestic_airport",
            label="nearest domestic airport",
            max_length=120,
        )
        normalized_staff_code = self._normalize_configured_text(
            staff_code,
            enabled=group.staff_code_enabled,
            field="staff_code",
            label="staff code",
            max_length=80,
        )
        normalized_meal_preference = self._normalize_meal_preference(
            meal_preference,
            enabled=group.meal_preference_enabled,
        )

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

        # Older upload clients placed group-option values inside
        # ``confirmed_fields`` as well as their dedicated request properties.
        # Ignore those known non-passport keys for backwards compatibility,
        # then strictly validate the passport-only payload.
        passport_fields = {
            key: value
            for key, value in confirmed_fields.items()
            if key
            not in {
                "base_city",
                "nearest_domestic_airport",
                "staff_code",
                "meal_preference",
            }
        }
        validate_reviewed_passport_payload(passport_fields)
        clean_fields = normalize_reviewed_passport_fields(passport_fields)
        if not any(clean_fields.values()):
            raise ValidationError("At least one reviewed field is required.", field="confirmed_fields")
        if normalized_base_city:
            clean_fields["base_city"] = normalized_base_city
        if normalized_staff_code:
            clean_fields["staff_code"] = normalized_staff_code
        if normalized_meal_preference:
            clean_fields["meal_preference"] = normalized_meal_preference

        if submission.status.value in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES:
            if (
                submission.post_submission_verification_revision >= 1
                and self._is_exact_replay(
                    submission,
                    clean_fields=clean_fields,
                    client_email=normalized_email,
                    client_phone=normalized_phone,
                    departure_city=normalized_departure_city,
                    nearest_domestic_airport=normalized_domestic_airport,
                    submission_mode=normalized_mode,
                    family_group_id=family_group_id,
                    family_member_index=family_member_index,
                    family_relation=normalized_relation,
                    family_gender=normalized_gender,
                    family_head_name=normalized_head_name,
                    family_head_email=normalized_head_email,
                    family_head_phone=normalized_head_phone,
                    family_broadcast_to_member=bool(
                        normalized_email or normalized_phone
                    ),
                )
            ):
                return replace(
                    passport_submission_output_from_entity(submission),
                    idempotent_replay=True,
                )
            raise ValidationError(
                "Passport details were already submitted.",
                field="submission_id",
            )

        draft_keys: list[str] = []
        promoted_keys: list[str] = []
        try:
            draft_key = submission.image_s3_key
            if draft_key.startswith("drafts/"):
                suffix = PurePosixPath(draft_key).suffix or ".jpg"
                permanent_key = f"{submission.agency_id}/{submission.group_id}/{submission.id}{suffix}"
                image = await self._storage_repo.get_file(draft_key)
                await self._storage_repo.upload_file(
                    image,
                    permanent_key,
                    self._content_type(suffix),
                )
                promoted_keys.append(permanent_key)
                submission.promote_image(permanent_key)
                draft_keys.append(draft_key)

            for document_type, current_key, promote in (
                ("photo", submission.passport_photo_s3_key, submission.promote_passport_photo),
                ("back", submission.passport_back_s3_key, submission.promote_passport_back),
            ):
                if not current_key or not current_key.startswith("drafts/"):
                    continue
                suffix = PurePosixPath(current_key).suffix or ".jpg"
                permanent_key = (
                    f"{submission.agency_id}/{submission.group_id}/"
                    f"{submission.id}-{document_type}{suffix}"
                )
                image = await self._storage_repo.get_file(current_key)
                await self._storage_repo.upload_file(
                    image,
                    permanent_key,
                    self._content_type(suffix),
                )
                promoted_keys.append(permanent_key)
                promote(permanent_key)
                draft_keys.append(current_key)

            submission.submit_client_review(
                clean_fields,
                client_email=normalized_email,
                client_phone=normalized_phone,
                departure_city=normalized_departure_city,
                nearest_domestic_airport=normalized_domestic_airport,
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
        except Exception:
            if promoted_keys:
                try:
                    await self._storage_repo.delete_files(promoted_keys)
                except Exception as cleanup_error:
                    logger.warning(
                        "passport_promotion_compensation_failed",
                        object_count=len(promoted_keys),
                        error_type=type(cleanup_error).__name__,
                    )
            raise

        return replace(
            passport_submission_output_from_entity(submission),
            storage_cleanup_keys=tuple(draft_keys),
            promoted_storage_keys=tuple(promoted_keys),
        )

    @staticmethod
    def _is_exact_replay(
        submission,  # type: ignore[no-untyped-def]
        *,
        clean_fields: dict[str, str],
        client_email: str | None,
        client_phone: str | None,
        departure_city: str | None,
        nearest_domestic_airport: str | None,
        submission_mode: str,
        family_group_id: uuid.UUID | None,
        family_member_index: int | None,
        family_relation: str | None,
        family_gender: str | None,
        family_head_name: str | None,
        family_head_email: str | None,
        family_head_phone: str | None,
        family_broadcast_to_member: bool,
    ) -> bool:
        return (
            dict(submission.confirmed_fields or {}) == clean_fields
            and submission.client_email == client_email
            and submission.client_phone == client_phone
            and submission.departure_city == departure_city
            and submission.nearest_domestic_airport
            == nearest_domestic_airport
            and submission.submission_mode == submission_mode
            and submission.family_group_id == family_group_id
            and submission.family_member_index == family_member_index
            and submission.family_relation == family_relation
            and submission.family_gender == family_gender
            and submission.family_head_name == family_head_name
            and submission.family_head_email == family_head_email
            and submission.family_head_phone == family_head_phone
            and submission.family_broadcast_to_member
            == family_broadcast_to_member
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
    def _normalize_departure_city(
        value: str | None,
        allowed_cities: list[str],
        *,
        enabled: bool,
    ) -> str | None:
        if not enabled:
            return None
        cities = [" ".join(city.strip().split()) for city in allowed_cities if city and city.strip()]
        if not cities:
            raise ValidationError(
                "No nearest international airports are configured for this group.",
                field="departure_city",
            )
        selected = " ".join(value.strip().split()) if value else ""
        if not selected:
            raise ValidationError("Select your nearest international airport.", field="departure_city")
        city_by_key = {city.casefold(): city for city in cities}
        matched = city_by_key.get(selected.casefold())
        if not matched:
            raise ValidationError("Select a valid nearest international airport for this group.", field="departure_city")
        return matched

    @staticmethod
    def _normalize_configured_text(
        value: str | None,
        *,
        enabled: bool,
        field: str,
        label: str,
        max_length: int,
    ) -> str | None:
        if not enabled:
            return None
        normalized = " ".join(value.strip().split())[:max_length] if value and value.strip() else ""
        if not normalized:
            raise ValidationError(f"Enter your {label}.", field=field)
        return normalized

    @staticmethod
    def _normalize_meal_preference(value: str | None, *, enabled: bool) -> str | None:
        if not enabled:
            return None
        normalized = " ".join(value.strip().split()).casefold() if value else ""
        meals = {"veg": "Veg", "non veg": "Non Veg", "jain": "Jain"}
        matched = meals.get(normalized)
        if not matched:
            raise ValidationError("Select Veg, Non Veg, or Jain.", field="meal_preference")
        return matched

    @staticmethod
    def _content_type(suffix: str) -> str:
        suffix = suffix.lower()
        if suffix == ".png":
            return "image/png"
        if suffix == ".webp":
            return "image/webp"
        return "image/jpeg"
