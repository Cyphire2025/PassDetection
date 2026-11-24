"""Durable email synchronization: events."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailArtifactModel,
    EmailMessageModel,
    EmailReviewItemModel,
)

from .sync_contracts import _ACTIVE_REVIEW_STATUSES


async def _refresh_message_counts(
    session: AsyncSession,
    message: EmailMessageModel,
) -> None:
    await session.flush()
    artifacts_result = await session.execute(
        select(
            func.count(EmailArtifactModel.id),
            func.count(EmailArtifactModel.id).filter(
                EmailArtifactModel.retrieval_status == "retrieved"
            ),
            func.count(EmailArtifactModel.id).filter(
                EmailArtifactModel.processing_status.in_({"completed", "duplicate", "ignored"})
            ),
            func.count(EmailArtifactModel.id).filter(
                EmailArtifactModel.processing_status == "failed"
            ),
        ).where(
            EmailArtifactModel.message_id == message.id,
            EmailArtifactModel.owner_user_id == message.owner_user_id,
        )
    )
    total, retrieved, processed, failures = artifacts_result.one()
    reviews = int(
        await session.scalar(
            select(func.count(EmailReviewItemModel.id)).where(
                EmailReviewItemModel.message_id == message.id,
                EmailReviewItemModel.owner_user_id == message.owner_user_id,
                EmailReviewItemModel.status.in_(_ACTIVE_REVIEW_STATUSES),
            )
        )
        or 0
    )
    message.artifact_count = int(total or 0)
    message.processed_artifact_count = int(processed or 0)
    message.review_count = reviews
    if message.relevance_status == "ignored":
        message.processing_status = "ignored"
    elif reviews:
        message.processing_status = "review_required"
    elif failures:
        message.processing_status = "partially_completed" if processed or retrieved else "failed"
    else:
        message.processing_status = "completed"
    message.processed_at = datetime.now(tz=UTC)
    message.updated_at = datetime.now(tz=UTC)


async def refresh_message_processing_state(
    session: AsyncSession,
    message: EmailMessageModel,
) -> None:
    """Recompute denormalized message state after a human review decision."""

    await _refresh_message_counts(session, message)


async def _advisory_transaction_lock(
    session: AsyncSession,
    lock_name: str,
) -> None:
    """Serialize cross-connection dedupe decisions on PostgreSQL.

    SQLite is used by focused tests and has no advisory locks. PostgreSQL's
    transaction-scoped lock is released automatically on commit or rollback.
    """

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    unsigned_key = int.from_bytes(
        hashlib.sha256(lock_name.encode("utf-8")).digest()[:8],
        byteorder="big",
        signed=False,
    )
    signed_key = unsigned_key if unsigned_key < 2**63 else unsigned_key - 2**64
    await session.execute(select(func.pg_advisory_xact_lock(signed_key)))


async def _record_event(
    session: AsyncSession,
    *,
    connection_id: uuid.UUID,
    agency_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    event_type: str,
    stage: str,
    summary_code: str,
    details: dict[str, object],
    message_id: uuid.UUID | None = None,
    artifact_id: uuid.UUID | None = None,
    review_item_id: uuid.UUID | None = None,
    actor_type: str = "system",
    actor_user_id: uuid.UUID | None = None,
    confidence: float | None = None,
    changed_entity_type: str | None = None,
    changed_entity_id: uuid.UUID | None = None,
    event_suffix: str = "1",
) -> None:
    event_key = (
        f"{message_id or connection_id}:{artifact_id or '-'}:"
        f"{review_item_id or '-'}:{event_type}:{event_suffix}"
    )[:255]
    existing = await session.scalar(
        select(EmailActivityEventModel.id).where(
            EmailActivityEventModel.agency_id == agency_id,
            EmailActivityEventModel.owner_user_id == owner_user_id,
            EmailActivityEventModel.event_key == event_key,
        )
    )
    if existing is not None:
        return
    now = datetime.now(tz=UTC)
    session.add(
        EmailActivityEventModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            owner_user_id=owner_user_id,
            connection_id=connection_id,
            message_id=message_id,
            artifact_id=artifact_id,
            review_item_id=review_item_id,
            event_key=event_key,
            event_type=event_type,
            stage=stage,
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            summary_code=summary_code,
            details=details,
            ai_used=False,
            confidence=confidence,
            changed_entity_type=changed_entity_type,
            changed_entity_id=changed_entity_id,
            occurred_at=now,
            created_at=now,
        )
    )
