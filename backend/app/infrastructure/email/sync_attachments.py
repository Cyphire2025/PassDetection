"""Durable email synchronization: attachments."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interfaces.email_provider import (
    EmailAttachment,
    EmailProvider,
    EmailProviderError,
    NormalizedEmailMessage,
)
from app.core.config.settings import Settings
from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.database.email_models import EmailArtifactModel, EmailMessageModel
from app.infrastructure.documents.document_matcher import DocumentMatcher
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations
from app.infrastructure.email.pdf_validator import (
    EmailPdfValidationError,
    EmailPdfValidator,
    ValidatedEmailPdf,
)
from app.infrastructure.security.upload_security import (
    DigestBoundScanner,
    UploadSecurityContext,
    UploadSecurityService,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository

from .sync_contracts import SyncClaim, _provider_artifact_id
from .sync_document_ingestion import _associate_and_route_document
from .sync_duplicates import (
    _is_reusable_duplicate_document,
    _live_duplicate_documents_statement,
    _reuse_live_duplicate_assignments,
)
from .sync_events import _advisory_transaction_lock
from .sync_reviews import _ensure_artifact_review


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
            EmailArtifactModel.agency_id == claim.agency_id,
            EmailArtifactModel.owner_user_id == claim.owner_user_id,
            EmailArtifactModel.provider_artifact_id == provider_artifact_id,
        )
        .with_for_update(of=EmailArtifactModel)
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        artifact = EmailArtifactModel(
            id=uuid.uuid4(),
            agency_id=claim.agency_id,
            owner_user_id=claim.owner_user_id,
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
        validated = await _validate_untrusted_email_pdf(
            content=content,
            filename=attachment.filename,
            declared_content_type=attachment.content_type,
            settings=settings,
            agency_id=claim.agency_id,
            user_id=claim.owner_user_id,
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
    duplicate_result = await session.execute(
        _live_duplicate_documents_statement(
            agency_id=claim.agency_id,
            owner_user_id=claim.owner_user_id,
            artifact_id=artifact.id,
            sha256_digest=validated.sha256_hex,
        )
    )
    duplicate_rows = [
        (source_artifact, document)
        for source_artifact, document in duplicate_result.all()
        if _is_reusable_duplicate_document(document)
    ]
    artifact.verified_content_type = validated.content_type
    artifact.size_bytes = len(validated.content)
    artifact.sha256_digest = validated.sha256_hex
    artifact.retrieval_status = "retrieved"
    artifact.retrieved_at = now
    if duplicate_rows:
        await _reuse_live_duplicate_assignments(
            session,
            claim=claim,
            message=stored_message,
            artifact=artifact,
            duplicate_rows=duplicate_rows,
            processed_at=now,
        )
        return []
    # A historical email hash without a still-assigned document is not a live
    # duplicate. This includes documents deleted by staff and PDFs retained
    # for review after their passenger assignment was removed.
    artifact.duplicate_of_id = None

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


async def _validate_untrusted_email_pdf(
    *,
    content: bytes,
    filename: str | None,
    declared_content_type: str | None,
    settings: Settings,
    agency_id: uuid.UUID,
    user_id: uuid.UUID,
    security_service: UploadSecurityService | None = None,
) -> ValidatedEmailPdf:
    """Scan and durably record provider bytes before any PDF parsing occurs."""

    service = security_service or UploadSecurityService(settings=settings)
    try:
        digest = await service.validate_document(
            content=content,
            declared_content_type=declared_content_type,
            context=UploadSecurityContext(
                ingestion_flow="email_attachment",
                agency_id=agency_id,
                user_id=user_id,
            ),
            max_bytes=settings.email_attachment_max_bytes,
        )
    except ImageValidationError:
        raise EmailPdfValidationError("Email attachment failed malware security scanning") from None
    validator = EmailPdfValidator(
        settings=settings,
        scanner=DigestBoundScanner(digest),
    )
    # Staff review also reaches this async boundary. Parse off the event loop
    # and drain the native work before cancellation releases the caller's scope.
    results = await run_bounded_storage_operations(
        [
            lambda: asyncio.to_thread(
                validator.validate,
                content=content,
                filename=filename,
                declared_content_type=declared_content_type,
            )
        ],
        concurrency=1,
    )
    return results[0]
