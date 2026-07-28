from __future__ import annotations

from app.application.interfaces.email_provider import (
    EmailChangeKind,
    EmailHistoryPage,
    EmailMessageChange,
)
from app.infrastructure.email.sync_service import (
    _can_ignore_without_artifact_inspection,
    _incremental_message_ids,
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


def test_unrelated_messages_with_artifacts_are_still_inspected() -> None:
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
    assert not _can_ignore_without_artifact_inspection(
        relevance_status="unrelated",
        has_attachments=False,
        has_links=True,
    )
