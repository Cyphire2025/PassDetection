"""
SQLAlchemy Passport Submission Repository
=========================================
Concrete implementation of IPassportSubmissionRepository.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.core.logging.logger import get_logger
from app.domain.entities.entities import (
    CONFIRMED_PASSPORT_STATUS_VALUES,
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    PENDING_REVIEW_PASSPORT_STATUS_VALUES,
    PassportExtractionStatus,
    PassportProcessingStatus,
    PassportSubmission,
    User,
)
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.domain.repositories.interfaces import (
    IPassportSubmissionRepository,
    PassportSubmissionGroupSummary,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    ManagerGroupAccessModel,
    PassportSubmissionModel,
)

logger = get_logger(__name__)


class PassportSubmissionRepository(IPassportSubmissionRepository):
    """SQLAlchemy implementation of IPassportSubmissionRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_entity(model: PassportSubmissionModel) -> PassportSubmission:
        return PassportSubmission(
            id=model.id,
            group_id=model.group_id,
            agency_id=model.agency_id,
            client_name=model.client_name,
            client_email=model.client_email,
            client_phone=model.client_phone,
            departure_city=model.departure_city,
            nearest_domestic_airport=model.nearest_domestic_airport,
            submission_mode=model.submission_mode,
            family_group_id=model.family_group_id,
            family_member_index=model.family_member_index,
            family_relation=model.family_relation,
            family_gender=model.family_gender,
            family_head_name=model.family_head_name,
            family_head_email=model.family_head_email,
            family_head_phone=model.family_head_phone,
            family_broadcast_to_member=model.family_broadcast_to_member,
            image_s3_key=model.image_s3_key,
            thumbnail_s3_key=model.thumbnail_s3_key,
            passport_photo_s3_key=model.passport_photo_s3_key,
            passport_back_s3_key=model.passport_back_s3_key,
            acquisition_mode=model.acquisition_mode,
            upload_idempotency_key=model.upload_idempotency_key,
            qualifier_enabled_snapshot=model.qualifier_enabled_snapshot,
            qualifier_selection_id=model.qualifier_selection_id,
            qualifier_is_self=model.qualifier_is_self,
            qualifier_relation_code=model.qualifier_relation_code,
            qualifier_relation_label=model.qualifier_relation_label,
            qualifier_selected_at=model.qualifier_selected_at,
            extraction_status=PassportExtractionStatus(model.extraction_status),
            extraction_revision=model.extraction_revision,
            staff_metadata=model.staff_metadata,
            custom_answers=list(model.custom_answers or []),
            custom_detail_answers=list(model.custom_detail_answers or []),
            status=PassportProcessingStatus(model.status),
            extracted_fields=model.extracted_fields,
            confirmed_fields=model.confirmed_fields,
            extraction_conflicts=list(model.extraction_conflicts or []),
            overall_confidence=model.overall_confidence,
            confidence_score=model.confidence_score,
            mrz_raw=model.mrz_raw,
            error_message=model.error_message,
            created_at=model.created_at,
            updated_at=model.updated_at,
            client_reviewed_at=model.client_reviewed_at,
            confirmed_at=model.confirmed_at,
            post_submission_verification=model.post_submission_verification,
            post_submission_verification_revision=(
                model.post_submission_verification_revision
            ),
            post_submission_verified_at=model.post_submission_verified_at,
            verification_reviewed_by_user_id=model.verification_reviewed_by_user_id,
            verification_reviewer_name=model.verification_reviewer_name,
            verification_reviewed_at=model.verification_reviewed_at,
        )

    @staticmethod
    def _to_model(entity: PassportSubmission) -> PassportSubmissionModel:
        return PassportSubmissionModel(
            id=entity.id,
            group_id=entity.group_id,
            agency_id=entity.agency_id,
            client_name=entity.client_name,
            client_email=entity.client_email,
            client_phone=entity.client_phone,
            departure_city=entity.departure_city,
            nearest_domestic_airport=entity.nearest_domestic_airport,
            submission_mode=entity.submission_mode,
            family_group_id=entity.family_group_id,
            family_member_index=entity.family_member_index,
            family_relation=entity.family_relation,
            family_gender=entity.family_gender,
            family_head_name=entity.family_head_name,
            family_head_email=entity.family_head_email,
            family_head_phone=entity.family_head_phone,
            family_broadcast_to_member=entity.family_broadcast_to_member,
            image_s3_key=entity.image_s3_key,
            thumbnail_s3_key=entity.thumbnail_s3_key,
            passport_photo_s3_key=entity.passport_photo_s3_key,
            passport_back_s3_key=entity.passport_back_s3_key,
            acquisition_mode=entity.acquisition_mode,
            upload_idempotency_key=entity.upload_idempotency_key,
            qualifier_enabled_snapshot=entity.qualifier_enabled_snapshot,
            qualifier_selection_id=entity.qualifier_selection_id,
            qualifier_is_self=entity.qualifier_is_self,
            qualifier_relation_code=entity.qualifier_relation_code,
            qualifier_relation_label=entity.qualifier_relation_label,
            qualifier_selected_at=entity.qualifier_selected_at,
            extraction_status=entity.extraction_status.value,
            extraction_revision=entity.extraction_revision,
            staff_metadata=entity.staff_metadata,
            custom_answers=entity.custom_answers,
            custom_detail_answers=entity.custom_detail_answers,
            status=entity.status.value,
            extracted_fields=entity.extracted_fields,
            confirmed_fields=entity.confirmed_fields,
            extraction_conflicts=entity.extraction_conflicts,
            overall_confidence=entity.overall_confidence,
            confidence_score=entity.confidence_score,
            mrz_raw=entity.mrz_raw,
            error_message=entity.error_message,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            client_reviewed_at=entity.client_reviewed_at,
            confirmed_at=entity.confirmed_at,
            post_submission_verification=entity.post_submission_verification,
            post_submission_verification_revision=(
                entity.post_submission_verification_revision
            ),
            post_submission_verified_at=entity.post_submission_verified_at,
            verification_reviewed_by_user_id=entity.verification_reviewed_by_user_id,
            verification_reviewer_name=entity.verification_reviewer_name,
            verification_reviewed_at=entity.verification_reviewed_at,
        )

    async def get_by_id(self, submission_id: uuid.UUID) -> PassportSubmission | None:
        result = await self._session.execute(
            select(PassportSubmissionModel).where(PassportSubmissionModel.id == submission_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_upload_idempotency_key(
        self,
        group_id: uuid.UUID,
        upload_idempotency_key: str,
    ) -> PassportSubmission | None:
        result = await self._session.execute(
            select(PassportSubmissionModel).where(
                PassportSubmissionModel.group_id == group_id,
                PassportSubmissionModel.upload_idempotency_key == upload_idempotency_key,
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_id_for_update(
        self,
        submission_id: uuid.UUID,
    ) -> PassportSubmission | None:
        """Lock one submission until the caller commits or rolls back."""

        result = await self._session.execute(
            select(PassportSubmissionModel)
            .where(PassportSubmissionModel.id == submission_id)
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def save(self, submission: PassportSubmission) -> PassportSubmission:
        model = self._to_model(submission)
        self._session.add(model)
        await self._session.flush()
        logger.info(
            "passport_submission_created",
            submission_id=str(submission.id),
            group_id=str(submission.group_id),
            agency_id=str(submission.agency_id),
        )
        return submission

    async def save_idempotent(
        self,
        submission: PassportSubmission,
    ) -> tuple[PassportSubmission, bool]:
        if not submission.upload_idempotency_key:
            return await self.save(submission), True

        model = self._to_model(submission)
        try:
            async with self._session.begin_nested():
                self._session.add(model)
                await self._session.flush()
        except IntegrityError:
            existing = await self.get_by_upload_idempotency_key(
                submission.group_id,
                submission.upload_idempotency_key,
            )
            if existing is None:
                raise
            logger.info(
                "passport_submission_idempotency_collision_resolved",
                submission_id=str(existing.id),
                group_id=str(existing.group_id),
            )
            return existing, False
        logger.info(
            "passport_submission_created",
            submission_id=str(submission.id),
            group_id=str(submission.group_id),
            agency_id=str(submission.agency_id),
        )
        return submission, True

    async def update(self, submission: PassportSubmission) -> PassportSubmission:
        result = await self._session.execute(
            select(PassportSubmissionModel).where(PassportSubmissionModel.id == submission.id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise EntityNotFoundError("PassportSubmission", str(submission.id))

        model.group_id = submission.group_id
        model.agency_id = submission.agency_id
        model.client_name = submission.client_name
        model.client_email = submission.client_email
        model.client_phone = submission.client_phone
        model.departure_city = submission.departure_city
        model.nearest_domestic_airport = submission.nearest_domestic_airport
        model.submission_mode = submission.submission_mode
        model.family_group_id = submission.family_group_id
        model.family_member_index = submission.family_member_index
        model.family_relation = submission.family_relation
        model.family_gender = submission.family_gender
        model.family_head_name = submission.family_head_name
        model.family_head_email = submission.family_head_email
        model.family_head_phone = submission.family_head_phone
        model.family_broadcast_to_member = submission.family_broadcast_to_member
        model.image_s3_key = submission.image_s3_key
        model.thumbnail_s3_key = submission.thumbnail_s3_key
        model.passport_photo_s3_key = submission.passport_photo_s3_key
        model.passport_back_s3_key = submission.passport_back_s3_key
        model.acquisition_mode = submission.acquisition_mode
        model.upload_idempotency_key = submission.upload_idempotency_key
        model.qualifier_enabled_snapshot = submission.qualifier_enabled_snapshot
        model.qualifier_selection_id = submission.qualifier_selection_id
        model.qualifier_is_self = submission.qualifier_is_self
        model.qualifier_relation_code = submission.qualifier_relation_code
        model.qualifier_relation_label = submission.qualifier_relation_label
        model.qualifier_selected_at = submission.qualifier_selected_at
        model.extraction_status = submission.extraction_status.value
        model.extraction_revision = submission.extraction_revision
        model.staff_metadata = submission.staff_metadata
        model.custom_answers = submission.custom_answers
        model.custom_detail_answers = submission.custom_detail_answers
        model.status = submission.status.value
        model.extracted_fields = submission.extracted_fields
        model.confirmed_fields = submission.confirmed_fields
        model.extraction_conflicts = submission.extraction_conflicts
        model.overall_confidence = submission.overall_confidence
        model.confidence_score = submission.confidence_score
        model.mrz_raw = submission.mrz_raw
        model.error_message = submission.error_message
        model.updated_at = submission.updated_at
        model.client_reviewed_at = submission.client_reviewed_at
        model.confirmed_at = submission.confirmed_at
        model.post_submission_verification = submission.post_submission_verification
        model.post_submission_verification_revision = (
            submission.post_submission_verification_revision
        )
        model.post_submission_verified_at = submission.post_submission_verified_at
        model.verification_reviewed_by_user_id = (
            submission.verification_reviewed_by_user_id
        )
        model.verification_reviewer_name = submission.verification_reviewer_name
        model.verification_reviewed_at = submission.verification_reviewed_at

        await self._session.flush()
        return submission

    async def apply_extraction_result(
        self,
        *,
        submission_id: uuid.UUID,
        expected_revision: int,
        extracted_fields: dict,
        confidence: float,
        confidence_score: dict | None,
        mrz_raw: str | None,
        review_threshold: float = 0.85,
    ) -> PassportSubmission | None:
        result = await self._session.execute(
            select(PassportSubmissionModel)
            .where(
                PassportSubmissionModel.id == submission_id,
                PassportSubmissionModel.extraction_revision == expected_revision,
            )
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        submission = self._to_entity(model)
        if not submission.mark_review_required(
            extracted_fields=extracted_fields,
            confidence=confidence,
            confidence_score=confidence_score,
            mrz_raw=mrz_raw,
            expected_revision=expected_revision,
            review_threshold=review_threshold,
        ):
            return None
        self._apply_extraction_fields(model, submission)
        await self._session.flush()
        return submission

    async def apply_extraction_failure(
        self,
        *,
        submission_id: uuid.UUID,
        expected_revision: int,
        public_message: str,
        diagnostics: dict[str, object] | None = None,
    ) -> PassportSubmission | None:
        result = await self._session.execute(
            select(PassportSubmissionModel)
            .where(
                PassportSubmissionModel.id == submission_id,
                PassportSubmissionModel.extraction_revision == expected_revision,
            )
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        submission = self._to_entity(model)
        if not submission.mark_extraction_failed(
            public_message,
            expected_revision=expected_revision,
            diagnostics=diagnostics,
        ):
            return None
        self._apply_extraction_fields(model, submission)
        await self._session.flush()
        return submission

    async def apply_post_submission_verification(
        self,
        *,
        submission_id: uuid.UUID,
        expected_revision: int,
        decision: str,
        verification: dict,
    ) -> PassportSubmission | None:
        result = await self._session.execute(
            select(PassportSubmissionModel)
            .where(
                PassportSubmissionModel.id == submission_id,
                PassportSubmissionModel.post_submission_verification_revision
                == expected_revision,
            )
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        submission = self._to_entity(model)
        if not submission.apply_post_submission_verification(
            expected_revision=expected_revision,
            decision=decision,
            verification=verification,
        ):
            return None
        model.status = submission.status.value
        model.post_submission_verification = submission.post_submission_verification
        model.post_submission_verified_at = submission.post_submission_verified_at
        model.updated_at = submission.updated_at
        await self._session.flush()
        return submission

    @staticmethod
    def _apply_extraction_fields(
        model: PassportSubmissionModel,
        submission: PassportSubmission,
    ) -> None:
        model.status = submission.status.value
        model.extraction_status = submission.extraction_status.value
        model.extracted_fields = submission.extracted_fields
        model.confirmed_fields = submission.confirmed_fields
        model.extraction_conflicts = submission.extraction_conflicts
        model.overall_confidence = submission.overall_confidence
        model.confidence_score = submission.confidence_score
        model.mrz_raw = submission.mrz_raw
        model.error_message = submission.error_message
        model.updated_at = submission.updated_at

    async def delete(self, submission_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(PassportSubmissionModel).where(PassportSubmissionModel.id == submission_id)
        )
        await self._session.flush()

    @staticmethod
    def _office_visible_statuses() -> tuple[str, ...]:
        return OFFICE_VISIBLE_PASSPORT_STATUS_VALUES

    @staticmethod
    def _status_filter_values(status_filter: str) -> tuple[str, ...]:
        if status_filter == PassportProcessingStatus.CONFIRMED.value:
            return CONFIRMED_PASSPORT_STATUS_VALUES
        if status_filter == PassportProcessingStatus.REVIEW_REQUIRED.value:
            return PENDING_REVIEW_PASSPORT_STATUS_VALUES
        if status_filter == PassportProcessingStatus.CLIENT_SUBMITTED.value:
            return OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
        return (status_filter,)

    @staticmethod
    def _apply_manager_group_scope(stmt, manager_id: uuid.UUID):  # type: ignore[no-untyped-def]
        return stmt.outerjoin(
            ManagerGroupAccessModel,
            (ManagerGroupAccessModel.group_id == ClientGroupModel.id)
            & (ManagerGroupAccessModel.manager_id == manager_id),
        ).where(
            or_(
                ClientGroupModel.created_by_user_id == manager_id,
                ManagerGroupAccessModel.manager_id == manager_id,
            )
        )

    async def list_by_agency(
        self,
        agency_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        search: str | None = None,
        exclude_archived_groups: bool = False,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> list[PassportSubmission]:
        stmt = select(PassportSubmissionModel).where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.status.in_(self._office_visible_statuses()),
        )
        if exclude_archived_groups or created_by_user_id or visible_to_user:
            stmt = stmt.join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
        if exclude_archived_groups:
            stmt = stmt.where(ClientGroupModel.status.notin_(["archived", "deleted"]))
        if created_by_user_id:
            stmt = self._apply_manager_group_scope(stmt, created_by_user_id)
        if visible_to_user:
            stmt = AuthorizationPolicy.apply_passport_visibility_scope(stmt, visible_to_user)
        if status_filter:
            stmt = stmt.where(
                PassportSubmissionModel.status.in_(
                    self._status_filter_values(status_filter)
                )
            )
        stmt = self._apply_search(stmt, search)
        stmt = stmt.order_by(PassportSubmissionModel.created_at.desc()).offset(skip).limit(limit)

        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_by_group(
        self,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int | None = 50,
        search: str | None = None,
        exclude_archived_groups: bool = False,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> list[PassportSubmission]:
        stmt = (
            select(PassportSubmissionModel)
            .join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
            .where(
                PassportSubmissionModel.agency_id == agency_id,
                PassportSubmissionModel.group_id == group_id,
                PassportSubmissionModel.status.in_(self._office_visible_statuses()),
            )
        )
        if exclude_archived_groups:
            stmt = stmt.where(ClientGroupModel.status.notin_(["archived", "deleted"]))
        if created_by_user_id:
            stmt = self._apply_manager_group_scope(stmt, created_by_user_id)
        if visible_to_user:
            stmt = AuthorizationPolicy.apply_passport_visibility_scope(stmt, visible_to_user)
        stmt = self._apply_search(stmt, search)
        stmt = stmt.order_by(PassportSubmissionModel.created_at.desc())
        if skip:
            stmt = stmt.offset(skip)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    def _apply_search(self, stmt, search: str | None):  # type: ignore[no-untyped-def]
        if not search or not search.strip():
            return stmt
        query = f"%{search.strip().lower()}%"
        return stmt.where(
            or_(
                func.lower(PassportSubmissionModel.client_name).like(query),
                func.lower(PassportSubmissionModel.client_email).like(query),
                func.lower(PassportSubmissionModel.client_phone).like(query),
                func.lower(PassportSubmissionModel.departure_city).like(query),
                func.lower(PassportSubmissionModel.extracted_fields["passport_number"].astext).like(query),
                func.lower(PassportSubmissionModel.confirmed_fields["passport_number"].astext).like(query),
                func.lower(PassportSubmissionModel.extracted_fields["surname"].astext).like(query),
                func.lower(PassportSubmissionModel.confirmed_fields["surname"].astext).like(query),
            )
        )

    async def list_group_summaries_by_agency(
        self,
        agency_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        exclude_archived_groups: bool = True,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> list[PassportSubmissionGroupSummary]:
        stmt = (
            select(
                ClientGroupModel.id.label("group_id"),
                ClientGroupModel.name.label("group_name"),
                ClientGroupModel.status.label("group_status"),
                ClientGroupModel.destination.label("destination"),
                ClientGroupModel.travel_date.label("travel_date"),
                ClientGroupModel.return_date.label("return_date"),
                ClientGroupModel.timezone.label("timezone"),
                ClientGroupModel.package_name.label("package_name"),
                ClientGroupModel.notes.label("notes"),
                ClientGroupModel.departure_cities.label("departure_cities"),
                ClientGroupModel.base_city_enabled.label("base_city_enabled"),
                ClientGroupModel.nearest_international_airport_enabled.label("nearest_international_airport_enabled"),
                ClientGroupModel.staff_code_enabled.label("staff_code_enabled"),
                ClientGroupModel.agent_employee_code_enabled.label(
                    "agent_employee_code_enabled"
                ),
                ClientGroupModel.meal_preference_enabled.label("meal_preference_enabled"),
                ClientGroupModel.require_selfie.label("require_selfie"),
                ClientGroupModel.allow_files_from_device.label("allow_files_from_device"),
                ClientGroupModel.ask_nearest_domestic_airport.label("ask_nearest_domestic_airport"),
                ClientGroupModel.relation_with_qualifier_enabled.label(
                    "relation_with_qualifier_enabled"
                ),
                ClientGroupModel.designation_enabled.label("designation_enabled"),
                ClientGroupModel.agency_dealership_name_enabled.label(
                    "agency_dealership_name_enabled"
                ),
                func.count(PassportSubmissionModel.id).label("total_passports"),
                func.sum(
                    case(
                        (
                            PassportSubmissionModel.status.in_(
                                PENDING_REVIEW_PASSPORT_STATUS_VALUES
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("pending_review_count"),
                func.sum(
                    case(
                        (
                            PassportSubmissionModel.status.in_(
                                CONFIRMED_PASSPORT_STATUS_VALUES
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("confirmed_count"),
                func.sum(
                    case((PassportSubmissionModel.status == PassportProcessingStatus.FAILED.value, 1), else_=0)
                ).label("failed_count"),
                func.coalesce(func.max(PassportSubmissionModel.updated_at), ClientGroupModel.created_at).label(
                    "latest_submission_at"
                ),
            )
            .outerjoin(
                PassportSubmissionModel,
                and_(
                    PassportSubmissionModel.group_id == ClientGroupModel.id,
                    PassportSubmissionModel.status.in_(self._office_visible_statuses()),
                ),
            )
            .where(ClientGroupModel.agency_id == agency_id)
        )
        if exclude_archived_groups:
            stmt = stmt.where(ClientGroupModel.status.notin_(["archived", "deleted"]))
        if created_by_user_id:
            stmt = self._apply_manager_group_scope(stmt, created_by_user_id)
        if visible_to_user:
            stmt = AuthorizationPolicy.apply_group_visibility_scope(stmt, visible_to_user)
        stmt = (
            stmt.group_by(
                ClientGroupModel.id,
                ClientGroupModel.name,
                ClientGroupModel.status,
                ClientGroupModel.destination,
                ClientGroupModel.travel_date,
                ClientGroupModel.return_date,
                ClientGroupModel.timezone,
                ClientGroupModel.package_name,
                ClientGroupModel.notes,
                ClientGroupModel.departure_cities,
                ClientGroupModel.base_city_enabled,
                ClientGroupModel.nearest_international_airport_enabled,
                ClientGroupModel.staff_code_enabled,
                ClientGroupModel.agent_employee_code_enabled,
                ClientGroupModel.meal_preference_enabled,
                ClientGroupModel.require_selfie,
                ClientGroupModel.allow_files_from_device,
                ClientGroupModel.ask_nearest_domestic_airport,
                ClientGroupModel.relation_with_qualifier_enabled,
                ClientGroupModel.designation_enabled,
                ClientGroupModel.agency_dealership_name_enabled,
                ClientGroupModel.created_at,
            )
            .order_by(func.coalesce(func.max(PassportSubmissionModel.updated_at), ClientGroupModel.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [
            PassportSubmissionGroupSummary(
                group_id=row.group_id,
                group_name=row.group_name,
                group_status=row.group_status,
                total_passports=int(row.total_passports),
                pending_review_count=int(row.pending_review_count or 0),
                confirmed_count=int(row.confirmed_count or 0),
                failed_count=int(row.failed_count or 0),
                latest_submission_at=row.latest_submission_at,
                destination=row.destination,
                travel_date=row.travel_date,
                return_date=row.return_date,
                timezone=row.timezone,
                package_name=row.package_name,
                departure_cities=list(row.departure_cities or []),
                base_city_enabled=row.base_city_enabled,
                nearest_international_airport_enabled=row.nearest_international_airport_enabled,
                staff_code_enabled=row.staff_code_enabled,
                agent_employee_code_enabled=row.agent_employee_code_enabled,
                meal_preference_enabled=row.meal_preference_enabled,
                require_selfie=row.require_selfie,
                allow_files_from_device=row.allow_files_from_device,
                ask_nearest_domestic_airport=row.ask_nearest_domestic_airport,
                relation_with_qualifier_enabled=(
                    row.relation_with_qualifier_enabled
                ),
                designation_enabled=row.designation_enabled,
                agency_dealership_name_enabled=(
                    row.agency_dealership_name_enabled
                ),
                notes=row.notes,
            )
            for row in result.all()
        ]

    async def exists_contact_in_group(
        self,
        group_id: uuid.UUID,
        *,
        client_email: str | None,
        client_phone: str | None,
        exclude_submission_id: uuid.UUID | None = None,
        scope: Literal["group", "platform"] = "group",
        additional_emails: Sequence[str] = (),
        additional_phones: Sequence[str] = (),
    ) -> bool:
        emails = tuple(
            dict.fromkeys(
                value for value in (client_email, *additional_emails) if value
            )
        )
        phones = tuple(
            dict.fromkeys(
                value for value in (client_phone, *additional_phones) if value
            )
        )
        if not emails and not phones:
            return False
        if scope not in {"group", "platform"}:
            raise ValueError("Unsupported duplicate contact scope")

        # Different submissions can otherwise pass the read-before-write check
        # concurrently. Transaction-scoped PostgreSQL advisory locks serialize
        # normalized contacts without requiring global lock rows.
        bind = self._session.get_bind()
        if bind.dialect.name == "postgresql":
            lock_scope = str(group_id) if scope == "group" else "platform"
            for contact in sorted((*emails, *phones)):
                digest = hashlib.blake2b(
                    f"passport-contact:{lock_scope}:{contact}".encode("utf-8"),
                    digest_size=8,
                ).digest()
                lock_key = int.from_bytes(digest, "big", signed=True)
                await self._session.execute(
                    select(func.pg_advisory_xact_lock(lock_key))
                )

        contact_filters: list[Any] = []
        if emails:
            contact_filters.extend(
                (
                    PassportSubmissionModel.client_email.in_(emails),
                    PassportSubmissionModel.family_head_email.in_(emails),
                )
            )
        if phones:
            contact_filters.extend(
                (
                    PassportSubmissionModel.client_phone.in_(phones),
                    PassportSubmissionModel.family_head_phone.in_(phones),
                )
            )
        stmt = select(PassportSubmissionModel.id).where(or_(*contact_filters))
        if scope == "group":
            stmt = stmt.where(PassportSubmissionModel.group_id == group_id)
        if exclude_submission_id:
            stmt = stmt.where(PassportSubmissionModel.id != exclude_submission_id)
        result = await self._session.execute(stmt.limit(1))
        return result.scalar_one_or_none() is not None

    async def count_by_agency(
        self,
        agency_id: uuid.UUID,
        *,
        status_filter: str | None = None,
        exclude_archived_groups: bool = False,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(PassportSubmissionModel).where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.status.in_(self._office_visible_statuses()),
        )
        if exclude_archived_groups or created_by_user_id or visible_to_user:
            stmt = stmt.join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
        if exclude_archived_groups:
            stmt = stmt.where(ClientGroupModel.status.notin_(["archived", "deleted"]))
        if created_by_user_id:
            stmt = self._apply_manager_group_scope(stmt, created_by_user_id)
        if visible_to_user:
            stmt = AuthorizationPolicy.apply_passport_visibility_scope(stmt, visible_to_user)
        if status_filter:
            stmt = stmt.where(
                PassportSubmissionModel.status.in_(
                    self._status_filter_values(status_filter)
                )
            )

        result = await self._session.execute(stmt)
        total = int(result.scalar_one())
        if not status_filter and not exclude_archived_groups and created_by_user_id is None and visible_to_user is None:
            historical_result = await self._session.execute(
                select(func.coalesce(func.sum(ClientGroupModel.deleted_passport_count), 0)).where(
                    ClientGroupModel.agency_id == agency_id,
                    ClientGroupModel.status == "deleted",
                    ClientGroupModel.deletion_retained_records.is_(False),
                )
            )
            total += int(historical_result.scalar_one() or 0)
        return total
