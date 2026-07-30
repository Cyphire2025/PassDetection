from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.infrastructure.documents.distribution_ingestion import (
    TravelDocumentFile,
    TravelDocumentIngestionService,
)
from app.infrastructure.documents.document_matcher import (
    ClassifiedDocument,
    MatchResult,
)


async def test_multiple_documents_for_one_passenger_are_all_preserved() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    passenger = SimpleNamespace(id=passenger_id)
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    matcher = MagicMock()
    matcher.classify.side_effect = [
        ClassifiedDocument(
            original_filename=filename,
            detected_type="visa",
            accepted=True,
            reason="Accepted",
            text="",
            extracted_name="ASHA MEHTA",
            extracted_passport_number="P1234567",
            extracted_reference=None,
        )
        for filename in ("first.pdf", "second.pdf")
    ]
    matcher.match_all.side_effect = [
        [
            MatchResult(
                passenger_id=passenger_id,
                confidence=0.99,
                status="matched",
                reason="Passport number matched",
            )
        ],
        [
            MatchResult(
                passenger_id=passenger_id,
                confidence=0.98,
                status="matched",
                reason="Passport number matched",
            )
        ],
    ]
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    audit_repository = MagicMock()
    audit_repository.record = AsyncMock()

    with patch(
        "app.infrastructure.documents.distribution_ingestion.AuditLogRepository",
        return_value=audit_repository,
    ):
        result = await TravelDocumentIngestionService(
            session,
            matcher=matcher,
            storage=storage,
        ).ingest(
            agency_id=agency_id,
            group_id=group_id,
            document_type="visa",
            passengers=[passenger],
            files=[
                TravelDocumentFile(filename="first.pdf", content=b"first"),
                TravelDocumentFile(filename="second.pdf", content=b"second"),
            ],
            created_by_user_id=None,
            actor_email=None,
        )

    assert len(result.documents) == 2
    assert {document.passenger_id for document in result.documents} == {passenger_id}
    assert {document.match_status for document in result.documents} == {"matched"}
    assert result.batch.uploaded_count == 2
    assert result.batch.matched_count == 2
