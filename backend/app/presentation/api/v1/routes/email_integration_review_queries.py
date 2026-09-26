"""Owner-scoped review projections and authorized assignment choices."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_models import (
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes import email_integration_review_support as _review_support
from app.presentation.api.v1.schemas.email_integration_schemas import (
    EmailReviewGroupOption,
    EmailReviewItemResponse,
    EmailReviewOptionsResponse,
    EmailReviewPassengerOption,
)

from .email_integration_access import (
    _agency_scope,
    _current_email_user,
    _email_owner_filters,
    _group_role_visibility_filter,
    _passport_role_visibility_filter,
)

router = APIRouter()

_string_list = _review_support._string_list
_allowed_review_actions = _review_support._allowed_review_actions
_display_conflicts = _review_support._display_conflicts
_passport_number_hint = _review_support._passport_number_hint


@router.get("/reviews", response_model=list[EmailReviewItemResponse])
async def list_email_reviews(
    review_status: str = Query(default="open", alias="status"),
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[EmailReviewItemResponse]:
    now = datetime.now(tz=UTC)
    if review_status not in {
        "open",
        "deferred",
        "resolved",
        "rejected",
        "cancelled",
        "all",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported review status.",
        )
    stmt = (
        select(
            EmailReviewItemModel,
            EmailMessageModel,
            EmailArtifactModel,
            ClientGroupModel.name,
            PassportSubmissionModel.client_name,
        )
        .join(
            EmailMessageModel,
            and_(
                EmailMessageModel.id == EmailReviewItemModel.message_id,
                EmailMessageModel.owner_user_id == EmailReviewItemModel.owner_user_id,
            ),
        )
        .outerjoin(
            EmailArtifactModel,
            and_(
                EmailArtifactModel.id == EmailReviewItemModel.artifact_id,
                EmailArtifactModel.owner_user_id == EmailReviewItemModel.owner_user_id,
            ),
        )
        .outerjoin(
            ClientGroupModel,
            and_(
                ClientGroupModel.id == EmailReviewItemModel.candidate_group_id,
                ClientGroupModel.agency_id == EmailReviewItemModel.agency_id,
                _group_role_visibility_filter(current_user),
            ),
        )
        .outerjoin(
            PassportSubmissionModel,
            and_(
                PassportSubmissionModel.id == EmailReviewItemModel.candidate_passenger_id,
                PassportSubmissionModel.agency_id == EmailReviewItemModel.agency_id,
                _passport_role_visibility_filter(current_user),
            ),
        )
        .where(
            *_email_owner_filters(
                EmailReviewItemModel.owner_user_id,
                EmailReviewItemModel.agency_id,
                current_user,
            ),
            EmailMessageModel.owner_user_id == current_user.id,
            or_(
                EmailArtifactModel.id.is_(None),
                EmailArtifactModel.owner_user_id == current_user.id,
            ),
        )
    )
    if review_status == "open":
        stmt = stmt.where(
            or_(
                EmailReviewItemModel.status == "open",
                (
                    (EmailReviewItemModel.status == "deferred")
                    & (EmailReviewItemModel.deferred_until.is_not(None))
                    & (EmailReviewItemModel.deferred_until <= now)
                ),
            )
        )
    elif review_status == "deferred":
        stmt = stmt.where(
            EmailReviewItemModel.status == "deferred",
            or_(
                EmailReviewItemModel.deferred_until.is_(None),
                EmailReviewItemModel.deferred_until > now,
            ),
        )
    elif review_status != "all":
        stmt = stmt.where(EmailReviewItemModel.status == review_status)
    result = await session.execute(stmt.order_by(EmailReviewItemModel.created_at.desc()).limit(250))
    responses: list[EmailReviewItemResponse] = []
    for review, message, artifact, group_name, passenger_name in result.all():
        responses.append(
            EmailReviewItemResponse(
                id=review.id,
                email_message_id=message.id,
                artifact_id=artifact.id if artifact else None,
                status=(
                    "open"
                    if (
                        review.status == "deferred"
                        and review.deferred_until is not None
                        and review.deferred_until <= now
                    )
                    else review.status
                ),
                review_type=review.review_type,
                sender_email=message.sender_address or "Unknown sender",
                subject=message.subject or "(No subject)",
                received_at=message.received_at,
                artifact_name=artifact.filename if artifact else None,
                artifact_kind=artifact.kind if artifact else None,
                artifact_detected_type=artifact.detected_type if artifact else None,
                proposed_group_id=(review.candidate_group_id if group_name is not None else None),
                proposed_group_name=group_name,
                proposed_passenger_id=(
                    review.candidate_passenger_id if passenger_name is not None else None
                ),
                proposed_passenger_name=passenger_name,
                confidence=float(review.confidence or 0.0),
                evidence=_string_list(review.evidence.get("signals", [])),
                conflicts=_display_conflicts(review.conflicts),
                proposed_action=review.proposed_action,
                allowed_actions=_allowed_review_actions(review, artifact),
                revision=review.revision,
                created_at=review.created_at,
            )
        )
    return responses


@router.get("/review-options", response_model=EmailReviewOptionsResponse)
async def email_review_options(
    group_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailReviewOptionsResponse:
    context_agency_id: uuid.UUID | None = None
    if message_id is not None:
        context_agency_id = (
            await session.execute(
                select(EmailMessageModel.agency_id)
                .join(
                    EmailConnectionModel,
                    and_(
                        EmailConnectionModel.id == EmailMessageModel.connection_id,
                        EmailConnectionModel.agency_id == EmailMessageModel.agency_id,
                        EmailConnectionModel.owner_user_id == EmailMessageModel.owner_user_id,
                    ),
                )
                .where(
                    EmailMessageModel.id == message_id,
                    EmailConnectionModel.owner_user_id == current_user.id,
                    *_email_owner_filters(
                        EmailMessageModel.owner_user_id,
                        EmailMessageModel.agency_id,
                        current_user,
                    ),
                )
            )
        ).scalar_one_or_none()
        if context_agency_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Email activity item was not found.",
            )

    groups_stmt = select(ClientGroupModel).where(
        ClientGroupModel.status.notin_({"archived", "deleted"})
    )
    if context_agency_id is not None:
        groups_stmt = groups_stmt.where(ClientGroupModel.agency_id == context_agency_id)
        groups_stmt = AuthorizationPolicy.apply_group_visibility_scope(
            groups_stmt,
            current_user,
        )
    elif current_user.role == UserRole.SUPER_ADMIN:
        groups_stmt = groups_stmt.where(
            ClientGroupModel.agency_id.in_(
                select(EmailConnectionModel.agency_id).where(
                    EmailConnectionModel.owner_user_id == current_user.id
                )
            )
        )
    else:
        _agency_scope(current_user)
        groups_stmt = AuthorizationPolicy.apply_group_visibility_scope(
            groups_stmt,
            current_user,
        )
    groups_result = await session.execute(groups_stmt.order_by(ClientGroupModel.created_at.desc()))
    groups = list(groups_result.scalars().all())
    passengers: list[PassportSubmissionModel] = []
    if group_id is not None:
        selected_group_stmt = select(ClientGroupModel).where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.status.notin_({"archived", "deleted"}),
        )
        if context_agency_id is not None:
            selected_group_stmt = selected_group_stmt.where(
                ClientGroupModel.agency_id == context_agency_id
            )
            selected_group_stmt = AuthorizationPolicy.apply_group_visibility_scope(
                selected_group_stmt,
                current_user,
            )
        elif current_user.role == UserRole.SUPER_ADMIN:
            selected_group_stmt = selected_group_stmt.where(
                ClientGroupModel.agency_id.in_(
                    select(EmailConnectionModel.agency_id).where(
                        EmailConnectionModel.owner_user_id == current_user.id
                    )
                )
            )
        else:
            selected_group_stmt = AuthorizationPolicy.apply_group_visibility_scope(
                selected_group_stmt,
                current_user,
            )
        selected_group = await session.scalar(selected_group_stmt)
        if selected_group is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client group was not found.",
            )
        passengers_stmt = select(PassportSubmissionModel).where(
            PassportSubmissionModel.agency_id == selected_group.agency_id,
            PassportSubmissionModel.group_id == group_id,
        )
        if current_user.role != UserRole.SUPER_ADMIN:
            passengers_stmt = AuthorizationPolicy.apply_passport_visibility_scope(
                passengers_stmt,
                current_user,
            )
        passengers_result = await session.execute(
            passengers_stmt.order_by(PassportSubmissionModel.client_name.asc()).limit(5_000)
        )
        passengers = list(passengers_result.scalars().all())
    return EmailReviewOptionsResponse(
        groups=[
            EmailReviewGroupOption(
                id=group.id,
                name=group.name,
                destination=group.destination,
                travel_date=group.travel_date,
            )
            for group in groups
        ],
        passengers=[
            EmailReviewPassengerOption(
                id=passenger.id,
                group_id=passenger.group_id,
                name=passenger.client_name,
                passport_number_hint=_passport_number_hint(passenger),
            )
            for passenger in passengers
        ],
    )
