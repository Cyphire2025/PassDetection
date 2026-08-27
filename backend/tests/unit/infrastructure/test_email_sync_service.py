from __future__ import annotations

import hashlib
import io
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from app.application.interfaces.email_provider import (
    EmailChangeKind,
    EmailHistoryPage,
    EmailMessageChange,
)
from app.core.config.settings import Settings
from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.email.pdf_validator import EmailPdfValidationError
from app.infrastructure.email.sync_service import (
    _can_ignore_without_artifact_inspection,
    _connection_claim_filters,
    _incremental_message_ids,
    _ingest_confirmed_artifact,
    _is_reusable_duplicate_document,
    _live_duplicate_documents_statement,
    _reuse_live_duplicate_assignments,
    _safe_link_hosts,
    _stored_relevance_status,
    _validate_untrusted_email_pdf,
)


class _HistoryProvider:
    def __init__(self, pages: list[EmailHistoryPage]) -> None:
        self.pages = pages
        self.calls: list[str | None] = []

    async def list_history_page(
        self,
        *,
        access_token: str,
        start_history_id: str,
        page_token: str | None = None,
        max_results: int = 100,
    ) -> EmailHistoryPage:
        del access_token, start_history_id, max_results
        self.calls.append(page_token)
        return self.pages[len(self.calls) - 1]


def _single_page_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


async def test_email_pdf_crosses_durable_security_boundary_before_parsing() -> None:
    content = _single_page_pdf()
    settings = SimpleNamespace(
        email_attachment_max_bytes=1024 * 1024,
        email_pdf_max_pages=10,
    )
    security_service = MagicMock()
    security_service.validate_document = AsyncMock(
        return_value=hashlib.sha256(content).hexdigest()
    )
    agency_id = uuid.uuid4()
    user_id = uuid.uuid4()

    result = await _validate_untrusted_email_pdf(
        content=content,
        filename="ticket.pdf",
        declared_content_type="application/pdf",
        settings=cast(Settings, settings),
        agency_id=agency_id,
        user_id=user_id,
        security_service=security_service,
    )

    assert result.content == content
    call = security_service.validate_document.await_args.kwargs
    assert call["content"] == content
    assert call["max_bytes"] == settings.email_attachment_max_bytes
    assert call["context"].ingestion_flow == "email_attachment"
    assert call["context"].agency_id == agency_id
    assert call["context"].user_id == user_id


async def test_email_pdf_security_failure_is_privacy_safe_and_prevents_parsing() -> None:
    security_service = MagicMock()
    security_service.validate_document = AsyncMock(
        side_effect=ImageValidationError("scanner secret diagnostic")
    )

    with pytest.raises(EmailPdfValidationError) as exc_info:
        await _validate_untrusted_email_pdf(
            content=b"raw-sensitive-provider-bytes",
            filename="ticket.pdf",
            declared_content_type="application/pdf",
            settings=cast(
                Settings,
                SimpleNamespace(
                    email_attachment_max_bytes=1024 * 1024,
                    email_pdf_max_pages=10,
                ),
            ),
            agency_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            security_service=security_service,
        )

    assert str(exc_info.value) == "Email attachment failed malware security scanning"


async def test_incremental_history_resumes_after_complete_bounded_page() -> None:
    first = EmailHistoryPage(
        changes=(
            EmailMessageChange("101", "message-1", EmailChangeKind.ADDED),
            EmailMessageChange("102", "message-2", EmailChangeKind.LABELS_CHANGED),
            EmailMessageChange("103", "deleted", EmailChangeKind.DELETED),
        ),
        next_page_token="next",
        latest_history_id="999",
        resume_history_id="103",
    )
    provider = _HistoryProvider([first])

    message_ids, cursor = await _incremental_message_ids(
        provider,  # type: ignore[arg-type]
        access_token="access",
        start_cursor="100",
        max_messages=1,
    )

    assert message_ids == ["message-1", "message-2"]
    assert cursor == "103"
    assert provider.calls == [None]


async def test_incremental_history_deduplicates_across_pages() -> None:
    provider = _HistoryProvider(
        [
            EmailHistoryPage(
                changes=(EmailMessageChange("101", "message-1", EmailChangeKind.ADDED),),
                next_page_token="next",
                latest_history_id="200",
            ),
            EmailHistoryPage(
                changes=(
                    EmailMessageChange(
                        "102",
                        "message-1",
                        EmailChangeKind.LABELS_CHANGED,
                    ),
                    EmailMessageChange("103", "message-2", EmailChangeKind.ADDED),
                ),
                next_page_token=None,
                latest_history_id="200",
            ),
        ]
    )

    message_ids, cursor = await _incremental_message_ids(
        provider,  # type: ignore[arg-type]
        access_token="access",
        start_cursor="100",
        max_messages=10,
    )

    assert message_ids == ["message-1", "message-2"]
    assert cursor == "200"
    assert provider.calls == [None, "next"]


def test_link_extraction_retains_hosts_not_signed_urls() -> None:
    body = (
        "Open https://portal.example.com/ticket?token=secret "
        "or https://portal.example.com/again and "
        "https://files.example.net/download/abc."
    )

    assert _safe_link_hosts(body) == [
        "portal.example.com",
        "files.example.net",
    ]


def test_relevance_status_maps_to_database_vocabulary() -> None:
    assert _stored_relevance_status("relevant") == "relevant"
    assert _stored_relevance_status("possibly_relevant") == "possible"
    assert _stored_relevance_status("unrelated") == "ignored"
    assert _stored_relevance_status("unexpected") == "pending"


def test_worker_claim_revalidates_the_complete_owner_envelope() -> None:
    claim = SimpleNamespace(
        connection_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        provider_account_id="provider-account",
        generation=7,
    )

    statement = select(EmailConnectionModel).where(*_connection_claim_filters(claim))
    parameters = statement.compile().params.values()

    assert claim.connection_id in parameters
    assert claim.agency_id in parameters
    assert claim.owner_user_id in parameters
    assert claim.provider_account_id in parameters
    assert claim.generation in parameters


def test_only_real_attachments_prevent_early_ignore() -> None:
    assert _can_ignore_without_artifact_inspection(
        relevance_status="unrelated",
        has_attachments=False,
        has_links=False,
    )
    assert not _can_ignore_without_artifact_inspection(
        relevance_status="unrelated",
        has_attachments=True,
        has_links=False,
    )
    assert _can_ignore_without_artifact_inspection(
        relevance_status="unrelated",
        has_attachments=False,
        has_links=True,
    )


async def test_confirmed_email_artifact_is_saved_in_canonical_ledger() -> None:
    agency_id = uuid.uuid4()
    owner_user_id = uuid.uuid4()
    connection_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    document_id = uuid.uuid4()
    batch = SimpleNamespace(status="draft", saved_at=None, updated_at=None)
    document = SimpleNamespace(
        id=document_id,
        storage_key="canonical/document.pdf",
    )
    ingestion = SimpleNamespace(
        batch=batch,
        documents=[document],
        rejected=[],
    )
    session = MagicMock()
    session.add = MagicMock()
    service = MagicMock()
    service.ingest = AsyncMock(return_value=ingestion)

    with (
        patch(
            "app.infrastructure.email.sync_service.PassportSubmissionRepository"
        ) as repository_class,
        patch(
            "app.infrastructure.email.sync_service.TravelDocumentIngestionService",
            return_value=service,
        ),
        patch(
            "app.infrastructure.email.sync_service._record_event",
            new=AsyncMock(),
        ),
    ):
        repository_class.return_value.list_by_group = AsyncMock(return_value=[])
        keys = await _ingest_confirmed_artifact(
            session,
            claim=SimpleNamespace(
                agency_id=agency_id,
                owner_user_id=owner_user_id,
                connection_id=connection_id,
            ),
            message=SimpleNamespace(id=uuid.uuid4()),
            artifact=SimpleNamespace(
                id=uuid.uuid4(),
                match_confidence=0.99,
            ),
            validated=SimpleNamespace(
                filename="visa.pdf",
                content=b"%PDF",
                content_type="application/pdf",
            ),
            document_type="visa",
            group_id=group_id,
            passenger_id=passenger_id,
            created_by_user_id=None,
            actor_email=None,
            result_type="created",
        )

    assert keys == ["canonical/document.pdf"]
    assert batch.status == "saved"
    assert batch.saved_at is not None
    assert session.add.call_count == 1


def test_only_still_matched_passenger_documents_block_exact_reprocessing() -> None:
    assigned = SimpleNamespace(passenger_id=uuid.uuid4(), match_status="matched")
    unassigned = SimpleNamespace(passenger_id=None, match_status="needs_review")
    uncertain = SimpleNamespace(
        passenger_id=uuid.uuid4(),
        match_status="needs_review",
    )

    assert _is_reusable_duplicate_document(assigned)
    assert not _is_reusable_duplicate_document(unassigned)
    assert not _is_reusable_duplicate_document(uncertain)

    statement = str(
        _live_duplicate_documents_statement(
            agency_id=uuid.uuid4(),
            owner_user_id=uuid.uuid4(),
            artifact_id=uuid.uuid4(),
            sha256_digest="a" * 64,
        )
    )
    assert "distributed_documents.passenger_id IS NOT NULL" in statement
    assert "distributed_documents.match_status =" in statement
    assert "email_artifact_documents" in statement


async def test_live_duplicate_reuses_existing_document_assignment() -> None:
    agency_id = uuid.uuid4()
    owner_user_id = uuid.uuid4()
    connection_id = uuid.uuid4()
    message_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    document_id = uuid.uuid4()
    source_artifact = SimpleNamespace(
        id=uuid.uuid4(),
        detected_type="visa",
    )
    document = SimpleNamespace(
        id=document_id,
        agency_id=agency_id,
        group_id=group_id,
        passenger_id=passenger_id,
        document_type="visa",
        match_status="matched",
        match_confidence=1.0,
    )
    artifact = SimpleNamespace(
        id=uuid.uuid4(),
        duplicate_of_id=None,
        group_id=None,
        passenger_id=None,
        detected_type="unknown",
        match_confidence=None,
        processing_status="processing",
        processed_at=None,
        error_code="old",
        error_message="old",
    )
    message = SimpleNamespace(
        id=message_id,
        group_id=None,
        relevance_status="possible",
        relevance_confidence=0.5,
        evidence_json={"signals": ["document_attachment"]},
    )
    session = MagicMock()
    session.add = MagicMock()
    processed_at = datetime.now(tz=UTC)

    with patch(
        "app.infrastructure.email.sync_service._record_event",
        new=AsyncMock(),
    ) as record_event:
        await _reuse_live_duplicate_assignments(
            session,
            claim=SimpleNamespace(
                agency_id=agency_id,
                owner_user_id=owner_user_id,
                connection_id=connection_id,
            ),
            message=message,
            artifact=artifact,
            duplicate_rows=[(source_artifact, document)],
            processed_at=processed_at,
        )

    assert artifact.duplicate_of_id == source_artifact.id
    assert artifact.group_id == group_id
    assert artifact.passenger_id == passenger_id
    assert artifact.detected_type == "visa"
    assert artifact.match_confidence == 1.0
    assert artifact.processing_status == "duplicate"
    assert artifact.processed_at == processed_at
    assert artifact.error_code is None
    assert artifact.error_message is None
    assert message.group_id == group_id
    assert message.relevance_status == "relevant"
    assert message.relevance_confidence == 0.94
    assert "existing_document_assignment" in message.evidence_json["signals"]
    linked_document = session.add.call_args.args[0]
    assert linked_document.artifact_id == artifact.id
    assert linked_document.distributed_document_id == document_id
    assert linked_document.result_type == "existing_duplicate"
    record_event.assert_awaited_once()
