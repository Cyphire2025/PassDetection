"""Durable Gmail synchronization and conservative document processing.

The service keeps provider I/O outside row locks, claims each connection with a
lease, and treats every provider message and artifact as an idempotent unit.
Email text is never executed or sent to an AI model in this first provider
slice.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.application.interfaces.email_provider import (
    EmailAttachment,
    EmailChangeKind,
    EmailProvider,
    EmailProviderAuthenticationError,
    EmailProviderError,
    EmailProviderResponseError,
    NormalizedEmailMessage,
)
from app.application.use_cases.email_integrations.matching import (
    GroupForAssociation,
    associate_group,
    associate_passenger,
)
from app.application.use_cases.email_integrations.relevance import decide_relevance
from app.core.config.settings import Settings, get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailArtifactDocumentModel,
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    DistributedDocumentModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.documents.distribution_ingestion import (
    TravelDocumentFile,
    TravelDocumentIngestionService,
)
from app.infrastructure.documents.document_matcher import (
    ClassifiedDocument,
    DocumentMatcher,
)
from app.infrastructure.email.gmail_provider import GmailEmailProvider
from app.infrastructure.email.pdf_validator import (
    EmailPdfValidationError,
    EmailPdfValidator,
    ValidatedEmailPdf,
)
from app.infrastructure.email.token_encryption import (
    EmailTokenCipher,
    EncryptedToken,
    TokenEncryptionError,
)
from app.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository

logger = get_logger(__name__)

_URL_PATTERN = re.compile(r"https?://([A-Za-z0-9.-]+)(?::\d+)?(?:[/?#][^\s<>]*)?", re.I)
_SUPPORTED_PDF_TYPES = {"visa", "flight_ticket"}
_ACTIVE_REVIEW_STATUSES = {"open", "deferred"}


@dataclass(frozen=True)
class SyncClaim:
    connection_id: uuid.UUID
    agency_id: uuid.UUID
    provider: str
    lease_token: str
    generation: int
    access_token: str
    refresh_token: str | None
    token_expires_at: datetime | None
    sync_cursor: str | None


@dataclass(frozen=True)
class SyncResult:
    connection_id: uuid.UUID
    processed_messages: int
    ignored_messages: int
    cursor_reset: bool


@dataclass(frozen=True)
class ReviewedArtifactIngestionResult:
    document_ids: tuple[uuid.UUID, ...]
    storage_keys: tuple[str, ...]
    duplicate: bool


def provider_for_connection(
    connection: EmailConnectionModel | SyncClaim,
    *,
    settings: Settings | None = None,
) -> EmailProvider:
    if connection.provider == "gmail":
        return GmailEmailProvider(settings=settings)
    raise EmailProviderResponseError(
        "The connected email provider is not supported",
        code="EMAIL_PROVIDER_UNSUPPORTED",
    )


async def run_connection_sync(
    connection_id: uuid.UUID,
    provider_message_id: str | None = None,
) -> SyncResult | None:
    """Claim and synchronize one connection in a worker-safe transaction flow."""

    settings = get_settings()
    if not (settings.email_integrations_enabled and settings.email_sync_enabled):
        return None

    claim: SyncClaim | None = None
    try:
        async with AsyncSessionFactory() as session:
            claim = await _claim_connection(session, connection_id, settings=settings)
            if claim is None:
                return None
        provider = provider_for_connection(claim, settings=settings)
    except (TokenEncryptionError, UnicodeDecodeError) as exc:
        await _record_connection_start_failure(
            connection_id,
            code="EMAIL_TOKEN_DECRYPTION_FAILED",
            message=("Stored email credentials could not be opened. Reconnect the email account."),
        )
        logger.error(
            "email_connection_credentials_unavailable",
            connection_id=str(connection_id),
            error_type=type(exc).__name__,
        )
        raise
    except EmailProviderError as exc:
        if claim is not None:
            await _record_connection_failure(
                claim,
                code=exc.code,
                message=str(exc),
                reconnect_required=exc.reconnect_required,
                retry_after_seconds=exc.retry_after_seconds,
                settings=settings,
            )
        else:
            await _record_connection_start_failure(
                connection_id,
                code=exc.code,
                message=str(exc),
            )
        raise

    processed = 0
    ignored = 0
    cursor_reset = False
    try:
        access_token, refresh_token, expires_at = await _fresh_access_token(
            claim,
            provider=provider,
            settings=settings,
        )

        message_ids: list[str]
        latest_cursor: str | None
        if provider_message_id:
            message_ids = [provider_message_id]
            latest_cursor = claim.sync_cursor
        elif claim.sync_cursor:
            try:
                message_ids, latest_cursor = await _incremental_message_ids(
                    provider,
                    access_token=access_token,
                    start_cursor=claim.sync_cursor,
                    max_messages=settings.email_sync_max_messages,
                )
            except EmailProviderResponseError as exc:
                if exc.code != "EMAIL_PROVIDER_HISTORY_CURSOR_INVALID":
                    raise
                cursor_reset = True
                message_ids, latest_cursor = await _initial_message_ids(
                    provider,
                    access_token=access_token,
                    settings=settings,
                )
        else:
            message_ids, latest_cursor = await _initial_message_ids(
                provider,
                access_token=access_token,
                settings=settings,
            )

        for provider_message_id in message_ids:
            if not await _renew_connection_lease(claim, settings=settings):
                break
            try:
                normalized = await provider.get_message(
                    access_token=access_token,
                    message_id=provider_message_id,
                )
            except EmailProviderResponseError as exc:
                if exc.status_code == 404:
                    ignored += 1
                    continue
                async with AsyncSessionFactory() as session:
                    recorded = await _record_unreadable_message(
                        session,
                        claim=claim,
                        provider_message_id=provider_message_id,
                        error_code=exc.code,
                    )
                    await session.commit()
                if not recorded:
                    break
                processed += 1
                continue
            if not await _renew_connection_lease(claim, settings=settings):
                break
            if "INBOX" not in normalized.labels:
                ignored += 1
                continue
            async with AsyncSessionFactory() as session:
                outcome = await _process_message(
                    session,
                    claim=claim,
                    provider=provider,
                    access_token=access_token,
                    message=normalized,
                    settings=settings,
                )
                await session.commit()
            if outcome == "stopped":
                break
            if outcome == "ignored":
                ignored += 1
            else:
                processed += 1

        async with AsyncSessionFactory() as session:
            await _finish_connection(
                session,
                claim=claim,
                cursor=latest_cursor or claim.sync_cursor,
                settings=settings,
            )
            await session.commit()
        return SyncResult(
            connection_id=connection_id,
            processed_messages=processed,
            ignored_messages=ignored,
            cursor_reset=cursor_reset,
        )
    except EmailProviderError as exc:
        await _record_connection_failure(
            claim,
            code=exc.code,
            message=str(exc),
            reconnect_required=exc.reconnect_required,
            retry_after_seconds=exc.retry_after_seconds,
            settings=settings,
        )
        raise
    except (TokenEncryptionError, EmailPdfValidationError) as exc:
        await _record_connection_failure(
            claim,
            code="EMAIL_SYNC_CONFIGURATION_ERROR",
            message=str(exc),
            reconnect_required=False,
            retry_after_seconds=None,
            settings=settings,
        )
        raise
    except Exception as exc:
        await _record_connection_failure(
            claim,
            code="EMAIL_SYNC_FAILED",
            message="Email synchronization failed before completion",
            reconnect_required=False,
            retry_after_seconds=None,
            settings=settings,
        )
        logger.error(
            "email_connection_sync_failed",
            connection_id=str(connection_id),
            error_type=type(exc).__name__,
        )
        raise


async def _claim_connection(
    session: AsyncSession,
    connection_id: uuid.UUID,
    *,
    settings: Settings,
) -> SyncClaim | None:
    now = datetime.now(tz=UTC)
    result = await session.execute(
        select(EmailConnectionModel)
        .options(
            undefer(EmailConnectionModel.access_token_ciphertext),
            undefer(EmailConnectionModel.refresh_token_ciphertext),
        )
        .where(EmailConnectionModel.id == connection_id)
        .with_for_update(skip_locked=True)
    )
    connection = result.scalar_one_or_none()
    if (
        connection is None
        or connection.status not in {"active", "failing"}
        or (connection.sync_lease_expires_at is not None and connection.sync_lease_expires_at > now)
        or not connection.access_token_ciphertext
    ):
        await session.rollback()
        return None

    cipher = EmailTokenCipher.from_settings(settings)
    access_token = cipher.decrypt(
        EncryptedToken(
            ciphertext=connection.access_token_ciphertext.decode("ascii"),
            key_version=connection.token_key_version,
        )
    )
    refresh_token = (
        cipher.decrypt(
            EncryptedToken(
                ciphertext=connection.refresh_token_ciphertext.decode("ascii"),
                key_version=connection.token_key_version,
            )
        )
        if connection.refresh_token_ciphertext
        else None
    )
    if connection.token_key_version != cipher.key_version:
        encrypted_access = cipher.encrypt(access_token)
        connection.access_token_ciphertext = encrypted_access.ciphertext.encode("ascii")
        if refresh_token is not None:
            encrypted_refresh = cipher.encrypt(refresh_token)
            connection.refresh_token_ciphertext = encrypted_refresh.ciphertext.encode("ascii")
        connection.token_key_version = cipher.key_version
    lease_token = uuid.uuid4().hex
    connection.sync_lease_token = lease_token
    connection.sync_lease_expires_at = now + timedelta(seconds=settings.email_sync_lease_seconds)
    connection.sync_state = "running"
    connection.last_sync_attempt_at = now
    connection.last_error_code = None
    connection.last_error_message = None
    await session.commit()
    return SyncClaim(
        connection_id=connection.id,
        agency_id=connection.agency_id,
        provider=connection.provider,
        lease_token=lease_token,
        generation=connection.sync_generation,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=connection.token_expires_at,
        sync_cursor=connection.sync_cursor,
    )


async def _fresh_access_token(
    claim: SyncClaim,
    *,
    provider: EmailProvider,
    settings: Settings,
) -> tuple[str, str | None, datetime | None]:
    now = datetime.now(tz=UTC)
    expires_at = claim.token_expires_at
    if expires_at is None or expires_at > now + timedelta(seconds=90):
        return claim.access_token, claim.refresh_token, expires_at
    if not claim.refresh_token:
        raise EmailProviderAuthenticationError(
            "The email connection must be reauthorized",
            code="EMAIL_PROVIDER_REFRESH_TOKEN_MISSING",
        )

    token_set = await provider.refresh_access_token(
        refresh_token=claim.refresh_token,
    )
    refresh_token = token_set.refresh_token or claim.refresh_token
    cipher = EmailTokenCipher.from_settings(settings)
    encrypted_access = cipher.encrypt(token_set.access_token)
    encrypted_refresh = cipher.encrypt(refresh_token)
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(EmailConnectionModel)
            .where(
                EmailConnectionModel.id == claim.connection_id,
                EmailConnectionModel.sync_lease_token == claim.lease_token,
                EmailConnectionModel.sync_generation == claim.generation,
            )
            .with_for_update()
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            raise EmailProviderResponseError(
                "The email connection changed while synchronization was running",
                code="EMAIL_CONNECTION_CHANGED",
            )
        connection.access_token_ciphertext = encrypted_access.ciphertext.encode("ascii")
        connection.refresh_token_ciphertext = encrypted_refresh.ciphertext.encode("ascii")
        connection.token_key_version = cipher.key_version
        connection.token_expires_at = token_set.expires_at
        if token_set.scopes:
            connection.scopes = list(token_set.scopes)
        await session.commit()
    return token_set.access_token, refresh_token, token_set.expires_at


async def _initial_message_ids(
    provider: EmailProvider,
    *,
    access_token: str,
    settings: Settings,
) -> tuple[list[str], str | None]:
    profile = await provider.get_account_profile(access_token=access_token)
    references = await provider.list_messages(
        access_token=access_token,
        query=f"in:inbox newer_than:{settings.email_sync_full_lookback_days}d",
        max_messages=settings.email_sync_max_messages,
    )
    return (
        list(dict.fromkeys(item.provider_message_id for item in references)),
        profile.history_cursor,
    )


async def _incremental_message_ids(
    provider: EmailProvider,
    *,
    access_token: str,
    start_cursor: str,
    max_messages: int,
) -> tuple[list[str], str]:
    message_ids: list[str] = []
    seen: set[str] = set()
    page_token: str | None = None
    latest_cursor = start_cursor
    for _ in range(1_000):
        page = await provider.list_history_page(
            access_token=access_token,
            start_history_id=start_cursor,
            page_token=page_token,
            max_results=100,
        )
        latest_cursor = page.latest_history_id
        for change in page.changes:
            if change.kind == EmailChangeKind.DELETED:
                continue
            if change.provider_message_id in seen:
                continue
            seen.add(change.provider_message_id)
            message_ids.append(change.provider_message_id)
        if not page.next_page_token:
            break
        if len(message_ids) >= max_messages:
            # The complete current history page is already represented in
            # message_ids. Resume from its last change instead of advancing to
            # Gmail's mailbox-wide latest cursor and skipping later pages.
            if page.changes:
                latest_cursor = page.changes[-1].provider_history_id
            break
        page_token = page.next_page_token
    else:
        raise EmailProviderResponseError(
            "Email history pagination exceeded its safety limit",
            code="EMAIL_PROVIDER_PAGINATION_INVALID",
        )
    return message_ids, latest_cursor


async def _renew_connection_lease(
    claim: SyncClaim,
    *,
    settings: Settings,
) -> bool:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(EmailConnectionModel)
            .where(
                EmailConnectionModel.id == claim.connection_id,
                EmailConnectionModel.sync_lease_token == claim.lease_token,
                EmailConnectionModel.sync_generation == claim.generation,
                EmailConnectionModel.status.in_({"active", "failing"}),
            )
            .with_for_update()
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            await session.rollback()
            return False
        connection.sync_lease_expires_at = datetime.now(tz=UTC) + timedelta(
            seconds=settings.email_sync_lease_seconds
        )
        await session.commit()
        return True


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
            EmailConnectionModel.id == claim.connection_id,
            EmailConnectionModel.sync_lease_token == claim.lease_token,
            EmailConnectionModel.sync_generation == claim.generation,
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
            EmailMessageModel.provider_message_id == provider_message_id,
        )
        .with_for_update()
    )
    if message is None:
        message = EmailMessageModel(
            id=uuid.uuid4(),
            agency_id=claim.agency_id,
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


async def _process_message(
    session: AsyncSession,
    *,
    claim: SyncClaim,
    provider: EmailProvider,
    access_token: str,
    message: NormalizedEmailMessage,
    settings: Settings,
) -> str:
    now = datetime.now(tz=UTC)
    valid_claim = await session.scalar(
        select(EmailConnectionModel)
        .where(
            EmailConnectionModel.id == claim.connection_id,
            EmailConnectionModel.sync_lease_token == claim.lease_token,
            EmailConnectionModel.sync_generation == claim.generation,
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
            EmailMessageModel.provider_message_id == message.provider_message_id,
        )
        .with_for_update()
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        stored = EmailMessageModel(
            id=uuid.uuid4(),
            agency_id=claim.agency_id,
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
    relevance = decide_relevance(
        subject=message.subject,
        body_text=message.plain_text_excerpt or message.snippet,
        attachment_filenames=filenames,
        detected_document_types=[],
    )
    stored.relevance_status = _stored_relevance_status(relevance.status)
    stored.relevance_confidence = relevance.confidence
    stored.evidence_json = {"signals": list(relevance.evidence)}

    await _record_event(
        session,
        connection_id=claim.connection_id,
        agency_id=claim.agency_id,
        message_id=stored.id,
        event_type="email_detected",
        stage="info",
        summary_code="EMAIL_DETECTED",
        details={"attachment_count": len(message.attachments)},
        event_suffix=message.history_id or "initial",
    )

    link_hosts = _safe_link_hosts(message.plain_text_excerpt)
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
                    EmailConnectionModel.id == claim.connection_id,
                    EmailConnectionModel.sync_lease_token == claim.lease_token,
                    EmailConnectionModel.sync_generation == claim.generation,
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


async def _process_attachment(
    session: AsyncSession,
    *,
    claim: SyncClaim,
    provider: EmailProvider,
    access_token: str,
    stored_message: EmailMessageModel,
    normalized_message: NormalizedEmailMessage,
    attachment: EmailAttachment,
    attachment_index: int,
    settings: Settings,
) -> list[str]:
    now = datetime.now(tz=UTC)
    provider_artifact_id = _provider_artifact_id(
        stored_message.provider_message_id,
        attachment_index,
        attachment.provider_attachment_id,
        attachment.filename,
    )
    result = await session.execute(
        select(EmailArtifactModel)
        .where(
            EmailArtifactModel.message_id == stored_message.id,
            EmailArtifactModel.provider_artifact_id == provider_artifact_id,
        )
        .with_for_update(of=EmailArtifactModel)
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        artifact = EmailArtifactModel(
            id=uuid.uuid4(),
            agency_id=claim.agency_id,
            message_id=stored_message.id,
            provider_artifact_id=provider_artifact_id,
            kind="inline" if attachment.disposition == "inline" else "attachment",
            provider_attachment_id=(
                attachment.provider_attachment_id[:768]
                if attachment.provider_attachment_id
                else None
            ),
            filename=attachment.filename[:500],
            declared_content_type=attachment.content_type[:255],
            size_bytes=attachment.size_bytes,
            retrieval_status="retrieving",
            processing_status="processing",
            detected_type="unknown",
            attempt_count=1,
            max_attempts=3,
            created_at=now,
            updated_at=now,
        )
        session.add(artifact)
        await session.flush()
    elif artifact.processing_status in {"completed", "duplicate", "ignored"}:
        return []
    else:
        artifact.attempt_count = min(artifact.attempt_count + 1, artifact.max_attempts)
        artifact.retrieval_status = "retrieving"
        artifact.processing_status = "processing"
        artifact.error_code = None
        artifact.error_message = None
        artifact.updated_at = now

    if not attachment.filename.casefold().endswith(".pdf"):
        artifact.retrieval_status = "blocked"
        artifact.processing_status = "review_required"
        artifact.error_code = "EMAIL_ATTACHMENT_TYPE_REQUIRES_REVIEW"
        artifact.error_message = (
            "Only validated PDF travel documents are automated in this provider release"
        )
        await _ensure_artifact_review(
            session,
            claim=claim,
            message=stored_message,
            artifact=artifact,
            review_type="retrieval",
            proposed_action="inspect_attachment",
            confidence=0.0,
            evidence=("unsupported_attachment_type",),
        )
        return []

    try:
        content = attachment.inline_content
        if content is None:
            if not attachment.provider_attachment_id:
                raise EmailPdfValidationError("The provider did not supply an attachment locator")
            content = await provider.get_attachment(
                access_token=access_token,
                message_id=normalized_message.provider_message_id,
                attachment_id=attachment.provider_attachment_id,
            )
        validated = EmailPdfValidator(settings=settings).validate(
            content=content,
            filename=attachment.filename,
            declared_content_type=attachment.content_type,
        )
    except EmailProviderError as exc:
        if exc.transient or exc.reconnect_required:
            raise
        artifact.retrieval_status = "failed"
        artifact.processing_status = "review_required"
        artifact.error_code = exc.code
        artifact.error_message = str(exc)[:1_000]
        artifact.last_error_at = now
        await _ensure_artifact_review(
            session,
            claim=claim,
            message=stored_message,
            artifact=artifact,
            review_type="processing_failure",
            proposed_action="retry_or_reject",
            confidence=0.0,
            evidence=("attachment_retrieval_or_validation_failed",),
        )
        return []
    except EmailPdfValidationError as exc:
        artifact.retrieval_status = "failed"
        artifact.processing_status = "review_required"
        artifact.error_code = "EMAIL_ATTACHMENT_VALIDATION_FAILED"
        artifact.error_message = str(exc)[:1_000]
        artifact.last_error_at = now
        await _ensure_artifact_review(
            session,
            claim=claim,
            message=stored_message,
            artifact=artifact,
            review_type="processing_failure",
            proposed_action="retry_or_reject",
            confidence=0.0,
            evidence=("attachment_retrieval_or_validation_failed",),
        )
        return []

    await _advisory_transaction_lock(
        session,
        f"email-content:{claim.agency_id}:{validated.sha256_hex}",
    )
    duplicate = await session.scalar(
        select(EmailArtifactModel)
        .where(
            EmailArtifactModel.agency_id == claim.agency_id,
            EmailArtifactModel.sha256_digest == validated.sha256_hex,
            EmailArtifactModel.id != artifact.id,
            EmailArtifactModel.processing_status.in_({"completed", "duplicate"}),
        )
        .order_by(EmailArtifactModel.created_at.asc())
        .limit(1)
    )
    artifact.verified_content_type = validated.content_type
    artifact.size_bytes = len(validated.content)
    artifact.sha256_digest = validated.sha256_hex
    artifact.retrieval_status = "retrieved"
    artifact.retrieved_at = now
    if duplicate is not None:
        artifact.duplicate_of_id = duplicate.id
        artifact.processing_status = "duplicate"
        artifact.processed_at = now
        await _record_event(
            session,
            connection_id=claim.connection_id,
            agency_id=claim.agency_id,
            message_id=stored_message.id,
            artifact_id=artifact.id,
            event_type="artifact_deduplicated",
            stage="success",
            summary_code="EMAIL_ARTIFACT_DEDUPLICATED",
            details={},
        )
        return []

    storage = MinioStorageRepository()
    created_staging_keys: list[str] = []
    storage_key = artifact.storage_key
    if storage_key is None:
        storage_key = (
            f"email-integrations/{claim.agency_id}/{stored_message.id}/"
            f"{artifact.id}-{validated.filename}"
        )
        await storage.upload_file(
            validated.content,
            storage_key,
            validated.content_type,
        )
        artifact.storage_key = storage_key
        created_staging_keys.append(storage_key)

    try:
        classification = DocumentMatcher().classify(
            filename=validated.filename,
            content=validated.content,
            expected_type="other",
        )
        artifact.detected_type = classification.detected_type
        canonical_keys = await _associate_and_route_document(
            session,
            claim=claim,
            message=stored_message,
            artifact=artifact,
            validated=validated,
            classification=classification,
            settings=settings,
        )
    except Exception:
        if created_staging_keys:
            artifact.storage_key = None
            await storage.delete_files(created_staging_keys)
        raise
    return [*created_staging_keys, *canonical_keys]


async def _associate_and_route_document(
    session: AsyncSession,
    *,
    claim: SyncClaim,
    message: EmailMessageModel,
    artifact: EmailArtifactModel,
    validated: ValidatedEmailPdf,
    classification: ClassifiedDocument,
    settings: Settings,
) -> list[str]:
    now = datetime.now(tz=UTC)
    groups_result = await session.execute(
        select(ClientGroupModel).where(
            ClientGroupModel.agency_id == claim.agency_id,
            ClientGroupModel.status.notin_({"archived", "deleted"}),
        )
    )
    group_models = list(groups_result.scalars().all())
    passengers = await PassportSubmissionRepository(session).list_by_agency(
        claim.agency_id,
        limit=5_000,
        exclude_archived_groups=True,
    )
    group_association = associate_group(
        email_text=f"{message.subject or ''} {message.body_excerpt or ''}",
        document=classification,
        groups=[
            GroupForAssociation(
                id=group.id,
                name=group.name,
                token=group.token,
                destination=group.destination,
                travel_date=group.travel_date,
            )
            for group in group_models
        ],
        passengers=passengers,
    )
    group_passengers = (
        [passenger for passenger in passengers if passenger.group_id == group_association.group_id]
        if group_association.group_id
        else passengers
    )
    passenger_association = associate_passenger(
        document=classification,
        passengers=group_passengers,
    )
    group_id = group_association.group_id
    passenger_id = passenger_association.passenger_id
    artifact.group_id = group_id
    artifact.passenger_id = passenger_id
    artifact.match_confidence = min(
        group_association.confidence,
        passenger_association.confidence,
    )
    message.group_id = group_id

    evidence = tuple(
        dict.fromkeys(
            [
                *group_association.evidence,
                *passenger_association.evidence,
                f"document_type_{classification.detected_type}",
            ]
        )
    )
    message.relevance_status = (
        "relevant" if classification.detected_type in _SUPPORTED_PDF_TYPES else "possible"
    )
    message.relevance_confidence = max(
        message.relevance_confidence or 0.0,
        0.94 if classification.detected_type in _SUPPORTED_PDF_TYPES else 0.5,
    )
    stored_signals = message.evidence_json.get("signals", [])
    existing_signals = (
        [item for item in stored_signals if isinstance(item, str)]
        if isinstance(stored_signals, list)
        else []
    )
    message.evidence_json = {"signals": list(dict.fromkeys([*existing_signals, *evidence]))}

    if classification.detected_type == "passport":
        artifact.processing_status = "review_required"
        await _ensure_artifact_review(
            session,
            claim=claim,
            message=message,
            artifact=artifact,
            review_type="passenger_match",
            proposed_action="route_passport_manually",
            confidence=artifact.match_confidence or 0.0,
            evidence=(*evidence, "passport_requires_gemini_upload_workflow"),
            candidate_group_id=group_id,
            candidate_passenger_id=passenger_id,
        )
        return []

    if classification.detected_type not in _SUPPORTED_PDF_TYPES:
        artifact.processing_status = "review_required"
        await _ensure_artifact_review(
            session,
            claim=claim,
            message=message,
            artifact=artifact,
            review_type="relevance",
            proposed_action="classify_document",
            confidence=artifact.match_confidence or 0.0,
            evidence=evidence,
            candidate_group_id=group_id,
            candidate_passenger_id=passenger_id,
        )
        return []

    if group_id is None or group_association.status != "matched":
        artifact.processing_status = "review_required"
        await _ensure_artifact_review(
            session,
            claim=claim,
            message=message,
            artifact=artifact,
            review_type="group_match",
            proposed_action="assign_group",
            confidence=group_association.confidence,
            evidence=evidence,
            candidate_group_id=group_id,
            candidate_passenger_id=passenger_id,
            alternatives=[
                {"group_id": str(group_id)} for group_id in group_association.candidate_group_ids
            ],
        )
        return []

    if passenger_id is None or passenger_association.status != "matched":
        artifact.processing_status = "review_required"
        await _ensure_artifact_review(
            session,
            claim=claim,
            message=message,
            artifact=artifact,
            review_type="passenger_match",
            proposed_action="assign_passenger",
            confidence=passenger_association.confidence,
            evidence=evidence,
            candidate_group_id=group_id,
            candidate_passenger_id=passenger_id,
            alternatives=[
                {"passenger_id": str(passenger_id)}
                for passenger_id in passenger_association.candidate_passenger_ids
            ],
        )
        return []

    await _advisory_transaction_lock(
        session,
        (
            f"email-document:{claim.agency_id}:{group_id}:"
            f"{passenger_id}:{classification.detected_type}"
        ),
    )
    existing_document = await session.scalar(
        select(DistributedDocumentModel)
        .where(
            DistributedDocumentModel.agency_id == claim.agency_id,
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.passenger_id == passenger_id,
            DistributedDocumentModel.document_type == classification.detected_type,
        )
        .order_by(DistributedDocumentModel.created_at.desc())
        .limit(1)
    )
    if existing_document is not None:
        artifact.processing_status = "review_required"
        await _ensure_artifact_review(
            session,
            claim=claim,
            message=message,
            artifact=artifact,
            review_type="possible_revision",
            proposed_action="confirm_revision",
            confidence=artifact.match_confidence or 0.0,
            evidence=(*evidence, "existing_passenger_document"),
            candidate_group_id=group_id,
            candidate_passenger_id=passenger_id,
            conflicts=[{"existing_document_id": str(existing_document.id)}],
        )
        return []

    if not settings.email_auto_actions_enabled:
        artifact.processing_status = "review_required"
        await _ensure_artifact_review(
            session,
            claim=claim,
            message=message,
            artifact=artifact,
            review_type="passenger_match",
            proposed_action="confirm_new_document",
            confidence=artifact.match_confidence or 0.0,
            evidence=(*evidence, "auto_actions_disabled"),
            candidate_group_id=group_id,
            candidate_passenger_id=passenger_id,
        )
        return []

    canonical_keys = await _ingest_confirmed_artifact(
        session,
        claim=claim,
        message=message,
        artifact=artifact,
        validated=validated,
        document_type=classification.detected_type,
        group_id=group_id,
        passenger_id=passenger_id,
        created_by_user_id=None,
        actor_email=None,
        result_type="created",
    )
    artifact.processing_status = "completed"
    artifact.processed_at = now
    return canonical_keys


async def ingest_reviewed_artifact(
    session: AsyncSession,
    *,
    review: EmailReviewItemModel,
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    actor_email: str,
) -> ReviewedArtifactIngestionResult:
    """Route a staff-confirmed staged PDF through the shared document pipeline."""

    result = await session.execute(
        select(EmailArtifactModel, EmailMessageModel, EmailConnectionModel)
        .join(
            EmailMessageModel,
            EmailMessageModel.id == EmailArtifactModel.message_id,
        )
        .join(
            EmailConnectionModel,
            EmailConnectionModel.id == EmailMessageModel.connection_id,
        )
        .where(
            EmailArtifactModel.id == review.artifact_id,
            EmailArtifactModel.agency_id == review.agency_id,
            EmailMessageModel.id == review.message_id,
        )
        .with_for_update(of=EmailArtifactModel)
    )
    row = result.one_or_none()
    if row is None:
        raise ValueError("The reviewed email artifact is no longer available")
    artifact, message, connection = row
    if not artifact.storage_key:
        raise ValueError("The reviewed email document is not available in storage")
    if artifact.detected_type not in _SUPPORTED_PDF_TYPES:
        raise ValueError("Choose a supported visa or flight ticket PDF")

    storage = MinioStorageRepository()
    content = await storage.get_file(artifact.storage_key)
    validated = EmailPdfValidator().validate(
        content=content,
        filename=artifact.filename,
        declared_content_type=artifact.verified_content_type,
    )
    artifact.sha256_digest = validated.sha256_hex
    artifact.verified_content_type = validated.content_type
    artifact.size_bytes = len(validated.content)
    await _advisory_transaction_lock(
        session,
        f"email-content:{review.agency_id}:{validated.sha256_hex}",
    )
    await _advisory_transaction_lock(
        session,
        (f"email-document:{review.agency_id}:{group_id}:{passenger_id}:{artifact.detected_type}"),
    )

    duplicate_result = await session.execute(
        select(
            EmailArtifactModel.id,
            EmailArtifactDocumentModel.distributed_document_id,
        )
        .join(
            EmailArtifactDocumentModel,
            EmailArtifactDocumentModel.artifact_id == EmailArtifactModel.id,
        )
        .join(
            DistributedDocumentModel,
            DistributedDocumentModel.id == EmailArtifactDocumentModel.distributed_document_id,
        )
        .where(
            EmailArtifactModel.agency_id == review.agency_id,
            EmailArtifactModel.sha256_digest == validated.sha256_hex,
            EmailArtifactModel.id != artifact.id,
            EmailArtifactModel.processing_status.in_({"completed", "duplicate"}),
            DistributedDocumentModel.agency_id == review.agency_id,
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.passenger_id == passenger_id,
            DistributedDocumentModel.document_type == artifact.detected_type,
        )
        .order_by(EmailArtifactModel.created_at.asc())
    )
    duplicate_rows = list(duplicate_result.all())
    if duplicate_rows:
        duplicate_artifact_id = duplicate_rows[0][0]
        document_ids = tuple(dict.fromkeys(row[1] for row in duplicate_rows))
        linked_ids = set(
            (
                await session.execute(
                    select(EmailArtifactDocumentModel.distributed_document_id).where(
                        EmailArtifactDocumentModel.artifact_id == artifact.id
                    )
                )
            )
            .scalars()
            .all()
        )
        for document_id in document_ids:
            if document_id in linked_ids:
                continue
            session.add(
                EmailArtifactDocumentModel(
                    id=uuid.uuid4(),
                    agency_id=review.agency_id,
                    artifact_id=artifact.id,
                    distributed_document_id=document_id,
                    result_type="existing_duplicate",
                    match_confidence=artifact.match_confidence,
                    match_evidence={
                        "source": "email_integration",
                        "human_confirmed": True,
                        "exact_content_duplicate": True,
                    },
                    created_at=datetime.now(tz=UTC),
                )
            )
        artifact.duplicate_of_id = duplicate_artifact_id
        artifact.group_id = group_id
        artifact.passenger_id = passenger_id
        artifact.processing_status = "duplicate"
        artifact.processed_at = datetime.now(tz=UTC)
        message.group_id = group_id
        await _record_event(
            session,
            connection_id=connection.id,
            agency_id=review.agency_id,
            message_id=message.id,
            artifact_id=artifact.id,
            event_type="artifact_deduplicated",
            stage="success",
            summary_code="EMAIL_ARTIFACT_DEDUPLICATED",
            details={"human_confirmed": True},
            actor_type="user",
            actor_user_id=created_by_user_id,
        )
        await _refresh_message_counts(session, message)
        return ReviewedArtifactIngestionResult(
            document_ids=document_ids,
            storage_keys=(),
            duplicate=True,
        )

    canonical_keys = await _ingest_confirmed_artifact(
        session,
        claim=SyncClaim(
            connection_id=connection.id,
            agency_id=review.agency_id,
            provider=connection.provider,
            lease_token="human-review",
            generation=connection.sync_generation,
            access_token="",
            refresh_token=None,
            token_expires_at=None,
            sync_cursor=None,
        ),
        message=message,
        artifact=artifact,
        validated=validated,
        document_type=artifact.detected_type,
        group_id=group_id,
        passenger_id=passenger_id,
        created_by_user_id=created_by_user_id,
        actor_email=actor_email,
        result_type="created",
    )
    try:
        artifact.group_id = group_id
        artifact.passenger_id = passenger_id
        artifact.processing_status = "completed"
        artifact.processed_at = datetime.now(tz=UTC)
        message.group_id = group_id
        await _refresh_message_counts(session, message)
        document_ids_result = await session.execute(
            select(EmailArtifactDocumentModel.distributed_document_id).where(
                EmailArtifactDocumentModel.artifact_id == artifact.id
            )
        )
    except Exception:
        await MinioStorageRepository().delete_files(canonical_keys)
        raise
    return ReviewedArtifactIngestionResult(
        document_ids=tuple(document_ids_result.scalars().all()),
        storage_keys=tuple(canonical_keys),
        duplicate=False,
    )


async def _ingest_confirmed_artifact(
    session: AsyncSession,
    *,
    claim: SyncClaim,
    message: EmailMessageModel,
    artifact: EmailArtifactModel,
    validated: ValidatedEmailPdf,
    document_type: str,
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    created_by_user_id: uuid.UUID | None,
    actor_email: str | None,
    result_type: str,
) -> list[str]:
    passengers = await PassportSubmissionRepository(session).list_by_group(
        claim.agency_id,
        group_id,
        limit=5_000,
        exclude_archived_groups=True,
    )
    result = await TravelDocumentIngestionService(session).ingest(
        agency_id=claim.agency_id,
        group_id=group_id,
        document_type=document_type,
        passengers=passengers,
        files=[
            TravelDocumentFile(
                filename=validated.filename,
                content=validated.content,
                content_type=validated.content_type,
            )
        ],
        created_by_user_id=created_by_user_id,
        actor_email=actor_email,
        forced_passenger_id=passenger_id,
        audit_source="email_integration",
        storage_prefix=(
            f"email-integrations-canonical/{claim.agency_id}/{message.id}/{artifact.id}"
        ),
    )
    if not result.documents:
        reason = (
            result.rejected[0].reason
            if result.rejected
            else "The selected file did not produce a travel document"
        )
        raise ValueError(reason)
    canonical_keys = list(dict.fromkeys(document.storage_key for document in result.documents))
    try:
        for document in result.documents:
            session.add(
                EmailArtifactDocumentModel(
                    id=uuid.uuid4(),
                    agency_id=claim.agency_id,
                    artifact_id=artifact.id,
                    distributed_document_id=document.id,
                    result_type=result_type,
                    match_confidence=artifact.match_confidence,
                    match_evidence={
                        "source": "email_integration",
                        "human_confirmed": created_by_user_id is not None,
                    },
                    created_at=datetime.now(tz=UTC),
                )
            )
        await _record_event(
            session,
            connection_id=claim.connection_id,
            agency_id=claim.agency_id,
            message_id=message.id,
            artifact_id=artifact.id,
            event_type="document_added",
            stage="success",
            summary_code="EMAIL_DOCUMENT_ADDED",
            details={
                "document_type": document_type,
                "document_count": len(result.documents),
            },
            actor_type="user" if created_by_user_id else "system",
            actor_user_id=created_by_user_id,
            changed_entity_type="passport_submission",
            changed_entity_id=passenger_id,
        )
    except Exception:
        await MinioStorageRepository().delete_files(canonical_keys)
        raise
    return canonical_keys


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
            EmailArtifactModel.provider_artifact_id == provider_artifact_id,
        )
    )
    if artifact is None:
        artifact = EmailArtifactModel(
            id=uuid.uuid4(),
            agency_id=claim.agency_id,
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
        ).where(EmailArtifactModel.message_id == message.id)
    )
    total, retrieved, processed, failures = artifacts_result.one()
    reviews = int(
        await session.scalar(
            select(func.count(EmailReviewItemModel.id)).where(
                EmailReviewItemModel.message_id == message.id,
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


async def _finish_connection(
    session: AsyncSession,
    *,
    claim: SyncClaim,
    cursor: str | None,
    settings: Settings,
) -> None:
    result = await session.execute(
        select(EmailConnectionModel)
        .where(
            EmailConnectionModel.id == claim.connection_id,
            EmailConnectionModel.sync_lease_token == claim.lease_token,
            EmailConnectionModel.sync_generation == claim.generation,
        )
        .with_for_update()
    )
    connection = result.scalar_one_or_none()
    if connection is None:
        return
    now = datetime.now(tz=UTC)
    connection.sync_cursor = cursor
    connection.status = "active"
    connection.sync_state = "idle"
    connection.sync_lease_token = None
    connection.sync_lease_expires_at = None
    connection.last_successful_sync_at = now
    connection.last_sync_completed_at = now
    connection.next_sync_at = now + timedelta(seconds=settings.email_sync_interval_seconds)
    connection.consecutive_failures = 0
    connection.last_error_code = None
    connection.last_error_message = None
    connection.last_error_at = None
    connection.updated_at = now


async def _record_connection_failure(
    claim: SyncClaim,
    *,
    code: str,
    message: str,
    reconnect_required: bool,
    retry_after_seconds: int | None,
    settings: Settings,
) -> None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(EmailConnectionModel)
            .where(
                EmailConnectionModel.id == claim.connection_id,
                EmailConnectionModel.sync_lease_token == claim.lease_token,
                EmailConnectionModel.sync_generation == claim.generation,
            )
            .with_for_update()
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            return
        now = datetime.now(tz=UTC)
        connection.consecutive_failures += 1
        connection.status = "expired" if reconnect_required else "failing"
        connection.sync_state = "blocked" if reconnect_required else "retry_wait"
        connection.sync_lease_token = None
        connection.sync_lease_expires_at = None
        connection.last_error_code = code[:80]
        connection.last_error_message = message[:1_000]
        connection.last_error_at = now
        backoff = retry_after_seconds or min(
            settings.email_sync_interval_seconds * (2 ** min(connection.consecutive_failures, 6)),
            86_400,
        )
        connection.next_sync_at = None if reconnect_required else now + timedelta(seconds=backoff)
        connection.updated_at = now
        await session.commit()


async def _record_connection_start_failure(
    connection_id: uuid.UUID,
    *,
    code: str,
    message: str,
) -> None:
    async with AsyncSessionFactory() as session:
        connection = await session.scalar(
            select(EmailConnectionModel)
            .where(EmailConnectionModel.id == connection_id)
            .with_for_update()
        )
        if connection is None or connection.status in {
            "paused",
            "disconnecting",
            "disconnected",
        }:
            return
        now = datetime.now(tz=UTC)
        connection.status = "expired"
        connection.sync_state = "blocked"
        connection.sync_lease_token = None
        connection.sync_lease_expires_at = None
        connection.next_sync_at = None
        connection.consecutive_failures += 1
        connection.last_error_code = code[:80]
        connection.last_error_message = message[:1_000]
        connection.last_error_at = now
        connection.updated_at = now
        await session.commit()


def _provider_artifact_id(
    provider_message_id: str,
    index: int,
    attachment_id: str | None,
    filename: str,
) -> str:
    if attachment_id:
        return f"attachment:{attachment_id}"[:768]
    return hashlib.sha256(f"{provider_message_id}|{index}|{filename}".encode("utf-8")).hexdigest()


def _stored_relevance_status(value: str) -> str:
    return {
        "relevant": "relevant",
        "possibly_relevant": "possible",
        "unrelated": "ignored",
    }.get(value, "pending")


def _can_ignore_without_artifact_inspection(
    *,
    relevance_status: str,
    has_attachments: bool,
    has_links: bool,
) -> bool:
    """Only ignore text-only messages that have no retrievable evidence."""

    return relevance_status == "unrelated" and not has_attachments and not has_links


def _safe_link_hosts(body: str) -> list[str]:
    hosts: list[str] = []
    for match in _URL_PATTERN.finditer(body[:8_000]):
        host = match.group(1).casefold().rstrip(".")[:253]
        if host and host not in hosts:
            hosts.append(host)
        if len(hosts) >= 20:
            break
    return hosts
