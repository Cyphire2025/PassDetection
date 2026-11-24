"""Durable email synchronization: messages."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interfaces.email_provider import EmailProvider, NormalizedEmailMessage
from app.application.use_cases.email_integrations.matching import (
    EmailContextAssociation,
    associate_email_context,
)
from app.application.use_cases.email_integrations.relevance import (
    decide_relevance,
    has_group_context_evidence,
)
from app.core.config.settings import Settings
from app.infrastructure.database.email_models import EmailConnectionModel, EmailMessageModel
from app.infrastructure.email.link_safety import safe_link_hosts as _safe_link_hosts
from app.infrastructure.storage.minio_repository import MinioStorageRepository

from .sync_attachments import _process_attachment
from .sync_contracts import (
    EmailRelevanceContext,
    SyncClaim,
    _can_ignore_without_artifact_inspection,
    _connection_claim_filters,
    _stored_relevance_status,
)
from .sync_events import _record_event, _refresh_message_counts
from .sync_reviews import _ensure_message_review, _upsert_blocked_link


async def _process_message(
    session: AsyncSession,
    *,
    claim: SyncClaim,
    provider: EmailProvider,
    access_token: str,
    message: NormalizedEmailMessage,
    settings: Settings,
    relevance_context: EmailRelevanceContext,
) -> str:
    now = datetime.now(tz=UTC)
    valid_claim = await session.scalar(
        select(EmailConnectionModel)
        .where(
            *_connection_claim_filters(claim),
            EmailConnectionModel.sync_lease_token == claim.lease_token,
            EmailConnectionModel.status.in_({"active", "failing"}),
        )
        .with_for_update()
    )
    if valid_claim is None:
        return "stopped"
    # Hold the connection row through this message transaction. Pause and
    # disconnect therefore wait for a clean message boundary and cannot race
    # a document write that was authorized by an obsolete generation.
    valid_claim.sync_lease_expires_at = now + timedelta(seconds=settings.email_sync_lease_seconds)
    result = await session.execute(
        select(EmailMessageModel)
        .where(
            EmailMessageModel.connection_id == claim.connection_id,
            EmailMessageModel.agency_id == claim.agency_id,
            EmailMessageModel.owner_user_id == claim.owner_user_id,
            EmailMessageModel.provider_message_id == message.provider_message_id,
        )
        .with_for_update()
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        stored = EmailMessageModel(
            id=uuid.uuid4(),
            agency_id=claim.agency_id,
            owner_user_id=claim.owner_user_id,
            connection_id=claim.connection_id,
            provider_message_id=message.provider_message_id,
            thread_id=message.thread_id,
            provider_history_id=message.history_id,
            sender_address=(message.sender.address[:320] if message.sender else None),
            sender_name=(
                message.sender.display_name[:255]
                if message.sender and message.sender.display_name
                else None
            ),
            recipients_json=[
                {"address": item.address, "display_name": item.display_name or ""}
                for item in (*message.to, *message.cc)
            ],
            subject=message.subject[:2_048],
            body_excerpt=(message.plain_text_excerpt or message.snippet)[:8_000],
            label_ids=list(message.labels),
            received_at=message.received_at or now,
            sent_at=None,
            has_attachments=bool(message.attachments),
            relevance_status="pending",
            relevance_confidence=None,
            evidence_json={},
            processing_status="processing",
            detected_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(stored)
        await session.flush()
    else:
        stored.thread_id = message.thread_id
        stored.provider_history_id = message.history_id
        stored.label_ids = list(message.labels)
        stored.updated_at = now
        if stored.processing_status in {"completed", "ignored"}:
            return "ignored" if stored.processing_status == "ignored" else "processed"
        stored.processing_status = "processing"

    filenames = [attachment.filename for attachment in message.attachments]
    context_association: EmailContextAssociation = associate_email_context(
        email_text=" ".join(
            [
                message.subject,
                message.plain_text_excerpt or message.snippet,
                message.sender.display_name
                if message.sender and message.sender.display_name
                else "",
                *[
                    " ".join(
                        part for part in (recipient.address, recipient.display_name or "") if part
                    )
                    for recipient in (*message.to, *message.cc)
                ],
                *filenames,
            ]
        ),
        sender_address=message.sender.address if message.sender else None,
        groups=list(relevance_context.groups),
        passengers=list(relevance_context.passengers),
    )
    relevance = decide_relevance(
        subject=message.subject,
        body_text=message.plain_text_excerpt or message.snippet,
        attachment_filenames=filenames,
        detected_document_types=[],
        deterministic_match_evidence=list(context_association.evidence),
    )
    if context_association.group_id is not None:
        stored.group_id = context_association.group_id
    stored.relevance_status = _stored_relevance_status(relevance.status)
    stored.relevance_confidence = relevance.confidence
    stored.evidence_json = {"signals": list(relevance.evidence)}

    await _record_event(
        session,
        connection_id=claim.connection_id,
        agency_id=claim.agency_id,
        owner_user_id=claim.owner_user_id,
        message_id=stored.id,
        event_type="email_detected",
        stage="info",
        summary_code="EMAIL_DETECTED",
        details={"attachment_count": len(message.attachments)},
        event_suffix=message.history_id or "initial",
    )

    link_hosts = _safe_link_hosts(message.plain_text_excerpt)
    if has_group_context_evidence(relevance.evidence):
        for index, host in enumerate(link_hosts):
            await _upsert_blocked_link(
                session,
                claim=claim,
                stored_message=stored,
                host=host,
                index=index,
            )

    if _can_ignore_without_artifact_inspection(
        relevance_status=relevance.status,
        has_attachments=bool(message.attachments),
        has_links=bool(link_hosts),
    ):
        stored.processing_status = "ignored"
        stored.processed_at = now
        await _refresh_message_counts(session, stored)
        return "ignored"

    if not settings.email_attachment_processing_enabled:
        if message.attachments:
            await _ensure_message_review(
                session,
                claim=claim,
                message=stored,
                review_type="retrieval",
                proposed_action="enable_attachment_processing",
                confidence=relevance.confidence,
                evidence=("attachment_processing_disabled",),
            )
        await _refresh_message_counts(session, stored)
        return "processed"

    attachments_to_process = message.attachments[: settings.email_max_artifacts_per_message]
    skipped_attachment_count = max(
        0,
        len(message.attachments) - settings.email_max_artifacts_per_message,
    )
    if skipped_attachment_count:
        await _ensure_message_review(
            session,
            claim=claim,
            message=stored,
            review_type="retrieval",
            proposed_action="inspect_source_email_for_additional_attachments",
            confidence=0.0,
            evidence=(
                "attachment_processing_limit_reached",
                f"attachments_skipped_{skipped_attachment_count}",
            ),
        )

    if not attachments_to_process:
        await _refresh_message_counts(session, stored)
        return "processed"

    # Persist the normalized envelope first, then give every attachment an
    # independent transaction. A malformed second item must not roll back a
    # successfully stored first item, and each advisory lock set is released
    # before the next attachment begins.
    stored.processing_status = "processing"
    await session.commit()

    for index, attachment in enumerate(attachments_to_process):
        created_storage_keys: list[str] = []
        try:
            current_claim = await session.scalar(
                select(EmailConnectionModel)
                .where(
                    *_connection_claim_filters(claim),
                    EmailConnectionModel.sync_lease_token == claim.lease_token,
                    EmailConnectionModel.status.in_({"active", "failing"}),
                )
                .with_for_update()
            )
            if current_claim is None:
                await session.rollback()
                return "stopped"
            current_claim.sync_lease_expires_at = datetime.now(tz=UTC) + timedelta(
                seconds=settings.email_sync_lease_seconds
            )
            current_message = await session.scalar(
                select(EmailMessageModel)
                .where(
                    EmailMessageModel.id == stored.id,
                    EmailMessageModel.agency_id == claim.agency_id,
                    EmailMessageModel.owner_user_id == claim.owner_user_id,
                    EmailMessageModel.connection_id == claim.connection_id,
                )
                .with_for_update()
            )
            if current_message is None:
                raise RuntimeError("The normalized email disappeared during processing")
            created_storage_keys = await _process_attachment(
                session,
                claim=claim,
                provider=provider,
                access_token=access_token,
                stored_message=current_message,
                normalized_message=message,
                attachment=attachment,
                attachment_index=index,
                settings=settings,
            )
            await _refresh_message_counts(session, current_message)
            if (
                index < len(attachments_to_process) - 1
                and current_message.processing_status == "completed"
            ):
                current_message.processing_status = "processing"
                current_message.processed_at = None
                current_message.updated_at = datetime.now(tz=UTC)
            await session.flush()
        except Exception:
            await session.rollback()
            if created_storage_keys:
                await MinioStorageRepository().delete_files(
                    list(dict.fromkeys(created_storage_keys))
                )
            raise
        try:
            await session.commit()
        except Exception:
            # COMMIT may have succeeded even when its acknowledgement was
            # lost. Keep uploaded objects; the orphan reconciler can safely
            # remove only keys that have no durable database reference.
            await session.rollback()
            raise

    return "processed"
