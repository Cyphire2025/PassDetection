"""
SQLAlchemy Passport Submission Repository
=========================================
Concrete implementation of IPassportSubmissionRepository.
"""

from __future__ import annotations

import uuid

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging.logger import get_logger
from app.domain.entities.entities import PassportProcessingStatus, PassportSubmission
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.domain.repositories.interfaces import IPassportSubmissionRepository, PassportSubmissionGroupSummary
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel

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
            image_s3_key=model.image_s3_key,
            thumbnail_s3_key=model.thumbnail_s3_key,
            status=PassportProcessingStatus(model.status),
            extracted_fields=model.extracted_fields,
            confirmed_fields=model.confirmed_fields,
            overall_confidence=model.overall_confidence,
            confidence_score=model.confidence_score,
            mrz_raw=model.mrz_raw,
            error_message=model.error_message,
            created_at=model.created_at,
            updated_at=model.updated_at,
            client_reviewed_at=model.client_reviewed_at,
            confirmed_at=model.confirmed_at,
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
            image_s3_key=entity.image_s3_key,
            thumbnail_s3_key=entity.thumbnail_s3_key,
            status=entity.status.value,
            extracted_fields=entity.extracted_fields,
            confirmed_fields=entity.confirmed_fields,
            overall_confidence=entity.overall_confidence,
            confidence_score=entity.confidence_score,
            mrz_raw=entity.mrz_raw,
            error_message=entity.error_message,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            client_reviewed_at=entity.client_reviewed_at,
            confirmed_at=entity.confirmed_at,
        )

    async def get_by_id(self, submission_id: uuid.UUID) -> PassportSubmission | None:
        result = await self._session.execute(
            select(PassportSubmissionModel).where(PassportSubmissionModel.id == submission_id)
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
            client_email=submission.client_email,
        )
        return submission

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
        model.image_s3_key = submission.image_s3_key
        model.thumbnail_s3_key = submission.thumbnail_s3_key
        model.status = submission.status.value
        model.extracted_fields = submission.extracted_fields
        model.confirmed_fields = submission.confirmed_fields
        model.overall_confidence = submission.overall_confidence
        model.confidence_score = submission.confidence_score
        model.mrz_raw = submission.mrz_raw
        model.error_message = submission.error_message
        model.updated_at = submission.updated_at
        model.client_reviewed_at = submission.client_reviewed_at
        model.confirmed_at = submission.confirmed_at

        await self._session.flush()
        return submission

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
    ) -> list[PassportSubmission]:
        stmt = select(PassportSubmissionModel).where(PassportSubmissionModel.agency_id == agency_id)
        if exclude_archived_groups or created_by_user_id:
            stmt = stmt.join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
        if exclude_archived_groups:
            stmt = stmt.where(ClientGroupModel.status != "archived")
        if created_by_user_id:
            stmt = stmt.where(ClientGroupModel.created_by_user_id == created_by_user_id)
        if status_filter:
            stmt = stmt.where(PassportSubmissionModel.status == status_filter)
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
        limit: int = 50,
        search: str | None = None,
        exclude_archived_groups: bool = False,
        created_by_user_id: uuid.UUID | None = None,
    ) -> list[PassportSubmission]:
        stmt = (
            select(PassportSubmissionModel)
            .join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
            .where(
                PassportSubmissionModel.agency_id == agency_id,
                PassportSubmissionModel.group_id == group_id,
            )
        )
        if exclude_archived_groups:
            stmt = stmt.where(ClientGroupModel.status != "archived")
        if created_by_user_id:
            stmt = stmt.where(ClientGroupModel.created_by_user_id == created_by_user_id)
        stmt = self._apply_search(stmt, search)
        stmt = stmt.order_by(PassportSubmissionModel.created_at.desc()).offset(skip).limit(limit)
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
    ) -> list[PassportSubmissionGroupSummary]:
        stmt = (
            select(
                ClientGroupModel.id.label("group_id"),
                ClientGroupModel.name.label("group_name"),
                ClientGroupModel.status.label("group_status"),
                func.count(PassportSubmissionModel.id).label("total_passports"),
                func.sum(
                    case((PassportSubmissionModel.status == PassportProcessingStatus.REVIEW_REQUIRED.value, 1), else_=0)
                ).label("pending_review_count"),
                func.sum(
                    case((PassportSubmissionModel.status == PassportProcessingStatus.CONFIRMED.value, 1), else_=0)
                ).label("confirmed_count"),
                func.sum(
                    case((PassportSubmissionModel.status == PassportProcessingStatus.FAILED.value, 1), else_=0)
                ).label("failed_count"),
                func.max(PassportSubmissionModel.updated_at).label("latest_submission_at"),
            )
            .join(PassportSubmissionModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
            .where(ClientGroupModel.agency_id == agency_id)
        )
        if exclude_archived_groups:
            stmt = stmt.where(ClientGroupModel.status != "archived")
        if created_by_user_id:
            stmt = stmt.where(ClientGroupModel.created_by_user_id == created_by_user_id)
        stmt = (
            stmt.group_by(ClientGroupModel.id, ClientGroupModel.name, ClientGroupModel.status)
            .order_by(func.max(PassportSubmissionModel.updated_at).desc())
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
            )
            for row in result.all()
        ]

    async def exists_contact_in_group(
        self,
        group_id: uuid.UUID,
        *,
        client_email: str,
        client_phone: str,
        exclude_submission_id: uuid.UUID | None = None,
    ) -> bool:
        stmt = select(PassportSubmissionModel.id).where(
            PassportSubmissionModel.group_id == group_id,
            or_(
                PassportSubmissionModel.client_email == client_email,
                PassportSubmissionModel.client_phone == client_phone,
            ),
        )
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
    ) -> int:
        stmt = select(func.count()).select_from(PassportSubmissionModel).where(PassportSubmissionModel.agency_id == agency_id)
        if exclude_archived_groups or created_by_user_id:
            stmt = stmt.join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
        if exclude_archived_groups:
            stmt = stmt.where(ClientGroupModel.status != "archived")
        if created_by_user_id:
            stmt = stmt.where(ClientGroupModel.created_by_user_id == created_by_user_id)
        if status_filter:
            stmt = stmt.where(PassportSubmissionModel.status == status_filter)

        result = await self._session.execute(stmt)
        return result.scalar_one()
