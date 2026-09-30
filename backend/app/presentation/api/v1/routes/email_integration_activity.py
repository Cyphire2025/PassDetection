"""Read-only mailbox summary, activity and message projections."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.email_integrations.overview import email_summary_day_start
from app.domain.entities.entities import User
from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailArtifactDocumentModel,
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
)
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.email_summary_repository import EmailSummaryRepository
from app.presentation.api.v1.routes import email_integration_review_support as _review_support
from app.presentation.api.v1.schemas.email_integration_schemas import (
    EmailActivityEventResponse,
    EmailActivityItemResponse,
    EmailArtifactDetailResponse,
    EmailIntegrationSummaryResponse,
    EmailMessageDetailResponse,
)

from .email_integration_access import (
    _agency_scope,
    _current_email_user,
    _email_owner_filters,
    _group_role_visibility_filter,
)

router = APIRouter()

_original_email_url = _review_support._original_email_url
_string_list = _review_support._string_list
_artifact_source_host = _review_support._artifact_source_host
_event_title = _review_support._event_title
_event_detail = _review_support._event_detail


@router.get("/summary", response_model=EmailIntegrationSummaryResponse)
async def email_integration_summary(
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailIntegrationSummaryResponse:
    _agency_scope(current_user)  # Preserve the website's missing-agency HTTP contract.
    counts = await EmailSummaryRepository(session).summary(current_user, today=email_summary_day_start())
    return EmailIntegrationSummaryResponse(**counts)


@router.get("/activity", response_model=list[EmailActivityItemResponse])
async def email_activity(
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[EmailActivityItemResponse]:
    result = await session.execute(
        select(
            EmailMessageModel,
            EmailConnectionModel.email_address,
            ClientGroupModel.name,
        )
        .join(
            EmailConnectionModel,
            and_(
                EmailConnectionModel.id == EmailMessageModel.connection_id,
                EmailConnectionModel.owner_user_id == EmailMessageModel.owner_user_id,
            ),
        )
        .outerjoin(
            ClientGroupModel,
            and_(
                ClientGroupModel.id == EmailMessageModel.group_id,
                ClientGroupModel.agency_id == EmailMessageModel.agency_id,
                _group_role_visibility_filter(current_user),
            ),
        )
        .where(
            *_email_owner_filters(
                EmailMessageModel.owner_user_id,
                EmailMessageModel.agency_id,
                current_user,
            )
        )
        .order_by(EmailMessageModel.received_at.desc())
        .limit(200)
    )
    rows = result.all()
    message_ids = [message.id for message, _, _ in rows]
    counts: dict[uuid.UUID, dict[str, int]] = {
        message_id: {"retrieved": 0, "matched": 0, "failed": 0} for message_id in message_ids
    }
    if message_ids:
        artifact_counts = await session.execute(
            select(
                EmailArtifactModel.message_id,
                func.count(func.distinct(EmailArtifactModel.id)).filter(
                    EmailArtifactModel.retrieval_status == "retrieved"
                ),
                func.count(func.distinct(EmailArtifactDocumentModel.id)),
                func.count(func.distinct(EmailArtifactModel.id)).filter(
                    EmailArtifactModel.retrieval_status == "failed"
                ),
            )
            .outerjoin(
                EmailArtifactDocumentModel,
                EmailArtifactDocumentModel.artifact_id == EmailArtifactModel.id,
            )
            .where(
                EmailArtifactModel.message_id.in_(message_ids),
                EmailArtifactModel.owner_user_id == current_user.id,
                or_(
                    EmailArtifactDocumentModel.id.is_(None),
                    EmailArtifactDocumentModel.owner_user_id == current_user.id,
                ),
            )
            .group_by(EmailArtifactModel.message_id)
        )
        for message_id, retrieved, matched, failed in artifact_counts.all():
            counts[message_id] = {
                "retrieved": int(retrieved or 0),
                "matched": int(matched or 0),
                "failed": int(failed or 0),
            }
    return [
        EmailActivityItemResponse(
            message_id=message.id,
            connection_id=message.connection_id,
            account_email=account_email,
            sender_email=message.sender_address or "Unknown sender",
            subject=message.subject or "(No subject)",
            received_at=message.received_at,
            relevance_status=message.relevance_status,
            processing_status=message.processing_status,
            group_name=group_name,
            retrieved_count=counts[message.id]["retrieved"],
            matched_count=counts[message.id]["matched"],
            review_count=message.review_count,
            failure_count=counts[message.id]["failed"],
        )
        for message, account_email, group_name in rows
    ]


@router.get("/messages/{message_id}", response_model=EmailMessageDetailResponse)
async def email_message_detail(
    message_id: uuid.UUID,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailMessageDetailResponse:
    row = (
        await session.execute(
            select(
                EmailMessageModel,
                EmailConnectionModel.email_address,
                EmailConnectionModel.provider,
                ClientGroupModel.name,
            )
            .join(
                EmailConnectionModel,
                and_(
                    EmailConnectionModel.id == EmailMessageModel.connection_id,
                    EmailConnectionModel.owner_user_id == EmailMessageModel.owner_user_id,
                ),
            )
            .outerjoin(
                ClientGroupModel,
                and_(
                    ClientGroupModel.id == EmailMessageModel.group_id,
                    ClientGroupModel.agency_id == EmailMessageModel.agency_id,
                    _group_role_visibility_filter(current_user),
                ),
            )
            .where(
                EmailMessageModel.id == message_id,
                *_email_owner_filters(
                    EmailMessageModel.owner_user_id,
                    EmailMessageModel.agency_id,
                    current_user,
                ),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email activity item was not found.",
        )
    message, account_email, provider, group_name = row
    artifacts = list(
        (
            await session.execute(
                select(EmailArtifactModel)
                .where(
                    EmailArtifactModel.message_id == message.id,
                    EmailArtifactModel.owner_user_id == current_user.id,
                )
                .order_by(EmailArtifactModel.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    events = list(
        (
            await session.execute(
                select(EmailActivityEventModel)
                .where(
                    EmailActivityEventModel.message_id == message.id,
                    EmailActivityEventModel.owner_user_id == current_user.id,
                )
                .order_by(EmailActivityEventModel.occurred_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return EmailMessageDetailResponse(
        id=message.id,
        connection_id=message.connection_id,
        account_email=account_email,
        sender_email=message.sender_address or "Unknown sender",
        sender_name=message.sender_name,
        recipients=[
            str(item.get("address", ""))
            for item in message.recipients_json
            if isinstance(item, dict) and item.get("address")
        ],
        subject=message.subject or "(No subject)",
        body_excerpt=message.body_excerpt or "",
        original_email_url=_original_email_url(
            provider=provider,
            account_email=account_email,
            provider_message_id=message.provider_message_id,
        ),
        received_at=message.received_at,
        relevance_status=message.relevance_status,
        relevance_confidence=float(message.relevance_confidence or 0.0),
        relevance_evidence=_string_list(message.evidence_json.get("signals", [])),
        processing_status=message.processing_status,
        group_id=message.group_id if group_name is not None else None,
        group_name=group_name,
        ai_used=message.ai_used,
        artifacts=[
            EmailArtifactDetailResponse(
                id=artifact.id,
                kind=artifact.kind,
                filename=artifact.filename,
                source_host=_artifact_source_host(artifact),
                verified_content_type=artifact.verified_content_type,
                byte_size=artifact.size_bytes,
                retrieval_status=artifact.retrieval_status,
                processing_status=artifact.processing_status,
                detected_type=artifact.detected_type,
                match_confidence=artifact.match_confidence,
                group_id=artifact.group_id,
                passenger_id=artifact.passenger_id,
                error_message=artifact.error_message,
            )
            for artifact in artifacts
        ],
        events=[
            EmailActivityEventResponse(
                id=event.id,
                event_type=event.event_type,
                status=event.stage,
                title=_event_title(event),
                detail=_event_detail(event),
                created_at=event.occurred_at,
            )
            for event in events
        ],
    )
