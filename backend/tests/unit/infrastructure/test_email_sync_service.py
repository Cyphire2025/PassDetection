from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.application.interfaces.email_provider import (
    EmailChangeKind,
    EmailHistoryPage,
    EmailMessageChange,
)
from app.infrastructure.email.sync_service import (
    _can_ignore_without_artifact_inspection,
    _incremental_message_ids,
    _ingest_confirmed_artifact,
    _safe_link_hosts,
    _stored_relevance_status,
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
