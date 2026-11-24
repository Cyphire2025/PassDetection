"""Durable email synchronization: reviews."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.email_models import (
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailReviewItemModel,
)
from app.infrastructure.repositories.notification_repository import NotificationRepository

from .sync_contracts import _ACTIVE_REVIEW_STATUSES, SyncClaim, _connection_claim_filters
from .sync_events import _record_event


async def _record_unreadable_message(
    session: AsyncSession,
    *,
    claim: SyncClaim,
    provider_message_id: str,
    error_code: str,
) -> bool:
    now = datetime.now(tz=UTC)
    valid_claim = await session.scalar(
        select(EmailConnectionModel.id)
        .where(
            *_connection_claim_filters(claim),
            EmailConnectionModel.sync_lease_token == claim.lease_token,
            EmailConnectionModel.status.in_({"active", "failing"}),
        )
        .with_for_update()
    )
    if valid_claim is None:
        return False
    message = await session.scalar(
        select(EmailMessageModel)
        .where(
            EmailMessageModel.connection_id == claim.connection_id,
            EmailMessageModel.agency_id == claim.agency_id,
            EmailMessageModel.owner_user_id == claim.owner_user_id,
            EmailMessageModel.provider_message_id == provider_message_id,
        )
        .with_for_update()
    )
    if message is None:
        message = EmailMessageModel(
            id=uuid.uuid4(),
            agency_id=claim.agency_id,
            owner_user_id=claim.owner_user_id,
            connection_id=claim.connection_id,
            provider_message_id=provider_message_id,
            recipients_json=[],
            subject="Email metadata could not be read",
            body_excerpt="",
            label_ids=[],
            received_at=now,
            has_attachments=False,
            relevance_status="failed",
            relevance_confidence=0.0,
            evidence_json={"signals": ["provider_message_unreadable"]},
            processing_status="failed",
            artifact_count=0,
            processed_artifact_count=0,
            review_count=1,
            ai_used=False,
            last_error_code=error_code[:80],
            detected_at=now,
            processed_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(message)
        await session.flush()
    else:
        message.relevance_status = "failed"
        message.processing_status = "failed"
        message.last_error_code = error_code[:80]
        message.updated_at = now
    await _ensure_message_review(
        session,
        claim=claim,
        message=message,
        review_type="processing_failure",
        proposed_action="retry_or_inspect_provider",
        confidence=0.0,
        evidence=("provider_message_unreadable",),
    )
    return True


async def _upsert_blocked_link(
    session: AsyncSession,
    *,
    claim: SyncClaim,
    stored_message: EmailMessageModel,
    host: str,
    index: int,
) -> None:
    provider_artifact_id = hashlib.sha256(
        f"{stored_message.provider_message_id}|link|{index}|{host}".encode()
    ).hexdigest()
    artifact = await session.scalar(
        select(EmailArtifactModel).where(
            EmailArtifactModel.message_id == stored_message.id,
            EmailArtifactModel.agency_id == claim.agency_id,
            EmailArtifactModel.owner_user_id == claim.owner_user_id,
            EmailArtifactModel.provider_artifact_id == provider_artifact_id,
        )
    )
    if artifact is None:
        artifact = EmailArtifactModel(
            id=uuid.uuid4(),
            agency_id=claim.agency_id,
            owner_user_id=claim.owner_user_id,
            message_id=stored_message.id,
            provider_artifact_id=provider_artifact_id,
            kind="direct_link",
            filename=f"Link from {host}"[:500],
            retrieval_status="blocked",
            processing_status="review_required",
            detected_type="unknown",
            attempt_count=0,
            max_attempts=3,
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
        session.add(artifact)
        await session.flush()
    await _ensure_artifact_review(
        session,
        claim=claim,
        message=stored_message,
        artifact=artifact,
        review_type="retrieval",
        proposed_action="open_provider_portal_manually",
        confidence=0.0,
        evidence=(f"link_host_{host}", "automatic_link_retrieval_blocked"),
    )


async def _ensure_message_review(
    session: AsyncSession,
    *,
    claim: SyncClaim,
    message: EmailMessageModel,
    review_type: str,
    proposed_action: str,
    confidence: float,
    evidence: Iterable[str],
) -> EmailReviewItemModel:
    return await _ensure_review(
        session,
        claim=claim,
        message=message,
        artifact=None,
        review_type=review_type,
        proposed_action=proposed_action,
        confidence=confidence,
        evidence=evidence,
    )


async def _ensure_artifact_review(
    session: AsyncSession,
    *,
    claim: SyncClaim,
    message: EmailMessageModel,
    artifact: EmailArtifactModel,
    review_type: str,
    proposed_action: str,
    confidence: float,
    evidence: Iterable[str],
    candidate_group_id: uuid.UUID | None = None,
    candidate_passenger_id: uuid.UUID | None = None,
    conflicts: list[dict[str, object]] | None = None,
    alternatives: list[dict[str, object]] | None = None,
) -> EmailReviewItemModel:
    return await _ensure_review(
        session,
        claim=claim,
        message=message,
        artifact=artifact,
        review_type=review_type,
        proposed_action=proposed_action,
        confidence=confidence,
        evidence=evidence,
        candidate_group_id=candidate_group_id,
        candidate_passenger_id=candidate_passenger_id,
        conflicts=conflicts,
        alternatives=alternatives,
    )


async def _ensure_review(
    session: AsyncSession,
    *,
    claim: SyncClaim,
    message: EmailMessageModel,
    artifact: EmailArtifactModel | None,
    review_type: str,
    proposed_action: str,
    confidence: float,
    evidence: Iterable[str],
    candidate_group_id: uuid.UUID | None = None,
    candidate_passenger_id: uuid.UUID | None = None,
    conflicts: list[dict[str, object]] | None = None,
    alternatives: list[dict[str, object]] | None = None,
) -> EmailReviewItemModel:
    conditions = [
        EmailReviewItemModel.agency_id == claim.agency_id,
        EmailReviewItemModel.owner_user_id == claim.owner_user_id,
        EmailReviewItemModel.message_id == message.id,
        EmailReviewItemModel.review_type == review_type,
        EmailReviewItemModel.status.in_(_ACTIVE_REVIEW_STATUSES),
    ]
    conditions.append(
        EmailReviewItemModel.artifact_id == artifact.id
        if artifact is not None
        else EmailReviewItemModel.artifact_id.is_(None)
    )
    review = await session.scalar(select(EmailReviewItemModel).where(*conditions).with_for_update())
    now = datetime.now(tz=UTC)
    if review is None:
        review = EmailReviewItemModel(
            id=uuid.uuid4(),
            agency_id=claim.agency_id,
            owner_user_id=claim.owner_user_id,
            message_id=message.id,
            artifact_id=artifact.id if artifact else None,
            review_type=review_type,
            status="open",
            proposed_action=proposed_action,
            confidence=max(0.0, min(confidence, 1.0)),
            evidence={"signals": list(dict.fromkeys(evidence))},
            conflicts=conflicts or [],
            alternatives=alternatives or [],
            proposed_payload={},
            candidate_group_id=candidate_group_id,
            candidate_passenger_id=candidate_passenger_id,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        session.add(review)
        await session.flush()
        await NotificationRepository(session).create(
            agency_id=claim.agency_id,
            user_id=claim.owner_user_id,
            type="email_review_required",
            title="Email document needs review",
            message="A retrieved email item needs a staff decision.",
            entity_type="email_review",
            entity_id=str(review.id),
        )
    else:
        next_confidence = max(0.0, min(confidence, 1.0))
        next_evidence: dict[str, object] = {"signals": list(dict.fromkeys(evidence))}
        next_conflicts = conflicts or []
        next_alternatives = alternatives or []
        proposal_changed = any(
            (
                review.proposed_action != proposed_action,
                review.confidence != next_confidence,
                review.evidence != next_evidence,
                review.conflicts != next_conflicts,
                review.alternatives != next_alternatives,
                review.candidate_group_id != candidate_group_id,
                review.candidate_passenger_id != candidate_passenger_id,
            )
        )
        review.proposed_action = proposed_action
        review.confidence = next_confidence
        review.evidence = next_evidence
        review.conflicts = next_conflicts
        review.alternatives = next_alternatives
        review.candidate_group_id = candidate_group_id
        review.candidate_passenger_id = candidate_passenger_id
        if proposal_changed:
            review.revision += 1
            review.updated_at = now
    await _record_event(
        session,
        connection_id=claim.connection_id,
        agency_id=claim.agency_id,
        owner_user_id=claim.owner_user_id,
        message_id=message.id,
        artifact_id=artifact.id if artifact else None,
        review_item_id=review.id,
        event_type="review_required",
        stage="warning",
        summary_code="EMAIL_REVIEW_REQUIRED",
        details={"review_type": review_type},
        confidence=review.confidence,
        event_suffix=str(review.revision),
    )
    return review
