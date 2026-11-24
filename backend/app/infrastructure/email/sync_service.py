"""Durable email synchronization: service."""

from __future__ import annotations

import uuid

from app.application.interfaces.email_provider import EmailProviderError, EmailProviderResponseError
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.email.link_safety import safe_link_hosts as _safe_link_hosts
from app.infrastructure.email.pdf_validator import EmailPdfValidationError
from app.infrastructure.email.token_encryption import TokenEncryptionError

from .sync_attachments import _process_attachment as _process_attachment
from .sync_attachments import _validate_untrusted_email_pdf as _validate_untrusted_email_pdf
from .sync_connections import (
    _claim_connection,
    _finish_connection,
    _fresh_access_token,
    _record_connection_failure,
    _record_connection_start_failure,
    _renew_connection_lease,
    provider_for_connection,
)
from .sync_contracts import _ACTIVE_REVIEW_STATUSES as _ACTIVE_REVIEW_STATUSES
from .sync_contracts import _SUPPORTED_PDF_TYPES as _SUPPORTED_PDF_TYPES
from .sync_contracts import EmailRelevanceContext as EmailRelevanceContext
from .sync_contracts import ReviewedArtifactIngestionResult as ReviewedArtifactIngestionResult
from .sync_contracts import SyncClaim, SyncResult
from .sync_contracts import (
    _can_ignore_without_artifact_inspection as _can_ignore_without_artifact_inspection,
)
from .sync_contracts import _connection_claim_filters as _connection_claim_filters
from .sync_contracts import _provider_artifact_id as _provider_artifact_id
from .sync_contracts import _stored_relevance_status as _stored_relevance_status
from .sync_document_ingestion import _associate_and_route_document as _associate_and_route_document
from .sync_document_ingestion import _ingest_confirmed_artifact as _ingest_confirmed_artifact
from .sync_duplicates import _is_reusable_duplicate_document as _is_reusable_duplicate_document
from .sync_duplicates import (
    _live_duplicate_documents_statement as _live_duplicate_documents_statement,
)
from .sync_duplicates import _reuse_live_duplicate_assignments as _reuse_live_duplicate_assignments
from .sync_events import _advisory_transaction_lock as _advisory_transaction_lock
from .sync_events import _record_event as _record_event
from .sync_events import _refresh_message_counts as _refresh_message_counts
from .sync_events import refresh_message_processing_state as refresh_message_processing_state
from .sync_mailbox import _incremental_message_ids, _initial_message_ids, _load_relevance_context
from .sync_messages import _process_message
from .sync_review_ingestion import ingest_reviewed_artifact as ingest_reviewed_artifact
from .sync_reviews import _ensure_artifact_review as _ensure_artifact_review
from .sync_reviews import _ensure_message_review as _ensure_message_review
from .sync_reviews import _ensure_review as _ensure_review
from .sync_reviews import _record_unreadable_message
from .sync_reviews import _upsert_blocked_link as _upsert_blocked_link

logger = get_logger("app.infrastructure.email.sync_service")


async def run_connection_sync(
    connection_id: uuid.UUID,
    provider_message_id: str | None = None,
    *,
    agency_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    provider_account_id: str,
    sync_generation: int,
) -> SyncResult | None:
    """Claim and synchronize one connection in a worker-safe transaction flow."""

    settings = get_settings()
    if not (settings.email_integrations_enabled and settings.email_sync_enabled):
        return None

    claim: SyncClaim | None = None
    try:
        async with AsyncSessionFactory() as session:
            claim = await _claim_connection(
                session,
                connection_id,
                agency_id=agency_id,
                owner_user_id=owner_user_id,
                provider_account_id=provider_account_id,
                sync_generation=sync_generation,
                settings=settings,
            )
            if claim is None:
                return None
        provider = provider_for_connection(claim, settings=settings)
    except (TokenEncryptionError, UnicodeDecodeError) as exc:
        await _record_connection_start_failure(
            connection_id,
            agency_id=agency_id,
            owner_user_id=owner_user_id,
            provider_account_id=provider_account_id,
            sync_generation=sync_generation,
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
                agency_id=agency_id,
                owner_user_id=owner_user_id,
                provider_account_id=provider_account_id,
                sync_generation=sync_generation,
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
        relevance_context = await _load_relevance_context(claim)

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
                    relevance_context=relevance_context,
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


__all__ = [
    "SyncClaim",
    "SyncResult",
    "ReviewedArtifactIngestionResult",
    "EmailRelevanceContext",
    "_connection_claim_filters",
    "_is_reusable_duplicate_document",
    "_live_duplicate_documents_statement",
    "provider_for_connection",
    "run_connection_sync",
    "_claim_connection",
    "_load_relevance_context",
    "_fresh_access_token",
    "_initial_message_ids",
    "_incremental_message_ids",
    "_renew_connection_lease",
    "_record_unreadable_message",
    "_process_message",
    "_process_attachment",
    "_reuse_live_duplicate_assignments",
    "_associate_and_route_document",
    "ingest_reviewed_artifact",
    "_ingest_confirmed_artifact",
    "_upsert_blocked_link",
    "_ensure_message_review",
    "_ensure_artifact_review",
    "_ensure_review",
    "_refresh_message_counts",
    "refresh_message_processing_state",
    "_advisory_transaction_lock",
    "_record_event",
    "_finish_connection",
    "_record_connection_failure",
    "_record_connection_start_failure",
    "_validate_untrusted_email_pdf",
    "_provider_artifact_id",
    "_stored_relevance_status",
    "_can_ignore_without_artifact_inspection",
    "_SUPPORTED_PDF_TYPES",
    "_ACTIVE_REVIEW_STATUSES",
    "_safe_link_hosts",
]
