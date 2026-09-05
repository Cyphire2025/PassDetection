from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infrastructure.documents import distribution_ingestion
from app.infrastructure.documents.distribution_capacity import (
    DocumentDistributionCapacityError,
)
from app.infrastructure.documents.distribution_ingestion import (
    TravelDocumentFile,
    TravelDocumentIngestionService,
)
from app.infrastructure.documents.document_matcher import (
    ClassifiedDocument,
    DocumentMatcher,
    MatchResult,
)


def _accepted_combined_document() -> ClassifiedDocument:
    return ClassifiedDocument(
        original_filename="combined.pdf",
        detected_type="visa",
        accepted=True,
        reason="Accepted",
        text="",
        extracted_name=None,
        extracted_passport_number=None,
        extracted_reference=None,
    )


def _matched_passengers(passenger_ids: list[uuid.UUID]) -> list[MatchResult]:
    return [
        MatchResult(
            passenger_id=passenger_id,
            confidence=0.98,
            status="matched",
            reason="PDF contains multiple uniquely identified passengers",
        )
        for passenger_id in passenger_ids
    ]


async def test_failed_dashboard_compensation_is_durably_tracked(monkeypatch) -> None:
    storage = MagicMock()
    storage.delete_files = AsyncMock(side_effect=RuntimeError("storage unavailable"))
    persist_cleanup = AsyncMock(return_value=uuid.uuid4())
    monkeypatch.setattr(
        distribution_ingestion,
        "persist_storage_cleanup_job",
        persist_cleanup,
    )
    service = TravelDocumentIngestionService(
        MagicMock(),
        storage=storage,
    )
    agency_id = uuid.uuid4()
    batch_id = uuid.uuid4()

    await service._cleanup_owned_storage(
        ["document-distribution/group/batch/visa.pdf"],
        agency_id=agency_id,
        batch_id=batch_id,
        durable=True,
    )

    persist_cleanup.assert_awaited_once_with(
        agency_id=agency_id,
        source="document_distribution_compensation",
        context_id=str(batch_id),
        storage_keys=["document-distribution/group/batch/visa.pdf"],
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
    assert len(result.created_storage_keys) == 2


async def test_dashboard_ingestion_rejects_a_verified_pdf_without_a_passenger_match() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger = SimpleNamespace(id=uuid.uuid4())
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    matcher = MagicMock()
    matcher.build_index.return_value = MagicMock()
    matcher.match_all.return_value = [
        MatchResult(
            passenger_id=None,
            confidence=0.0,
            status="needs_review",
            reason="No passenger match found",
        )
    ]
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    storage.copy_file = AsyncMock()
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
            document_type="flight_ticket",
            passengers=[passenger],
            files=[TravelDocumentFile(filename="unmatched.pdf", content=b"")],
            created_by_user_id=None,
            actor_email=None,
            preclassified_documents=[
                ClassifiedDocument(
                    original_filename="unmatched.pdf",
                    detected_type="flight_ticket",
                    accepted=True,
                    reason="Verified flight ticket structure",
                    text="E-TICKET",
                    extracted_name=None,
                    extracted_passport_number=None,
                    extracted_reference=None,
                )
            ],
            staged_storage_keys=[f"document-verification-staging/{agency_id}/unmatched.pdf"],
            require_passenger_match=True,
        )

    storage.upload_file.assert_not_awaited()
    storage.copy_file.assert_not_awaited()
    assert result.documents == []
    assert result.created_storage_keys == ()
    assert result.batch.uploaded_count == 0
    assert result.batch.matched_count == 0
    assert result.batch.rejected_count == 1
    assert result.rejected[0].reason == "No passenger match found"


async def test_staged_document_skips_second_parse_and_copies_server_side(
    monkeypatch,
) -> None:
    agency_id, group_id, passenger_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    passenger = SimpleNamespace(id=passenger_id)
    classification = ClassifiedDocument(
        original_filename="verified.pdf",
        detected_type="visa",
        accepted=True,
        reason="Verified visa structure",
        text="already extracted during verification",
        extracted_name="Asha Mehta",
        extracted_passport_number="P1234567",
        extracted_reference="EV123456",
    )
    source_key = f"document-verification-staging/{agency_id}/{uuid.uuid4()}/{uuid.uuid4()}.pdf"
    classify = MagicMock(side_effect=AssertionError("PDF must not be parsed twice"))
    monkeypatch.setattr(distribution_ingestion, "classify_documents_bounded", classify)
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    storage = MagicMock()
    storage.copy_file = AsyncMock()
    storage.upload_file = AsyncMock()
    audit_repository = MagicMock()
    audit_repository.record = AsyncMock()

    with patch(
        "app.infrastructure.documents.distribution_ingestion.AuditLogRepository",
        return_value=audit_repository,
    ):
        result = await TravelDocumentIngestionService(
            session,
            storage=storage,
        ).ingest(
            agency_id=agency_id,
            group_id=group_id,
            document_type="visa",
            passengers=[passenger],
            files=[TravelDocumentFile(filename="verified.pdf", content=b"")],
            created_by_user_id=None,
            actor_email=None,
            forced_passenger_id=passenger_id,
            preclassified_documents=[classification],
            staged_storage_keys=[source_key],
        )

    classify.assert_not_called()
    storage.upload_file.assert_not_awaited()
    storage.copy_file.assert_awaited_once()
    assert storage.copy_file.await_args.args[0] == source_key
    destination_key = storage.copy_file.await_args.args[1]
    assert destination_key.startswith(f"document-distribution/{group_id}/")
    assert destination_key != source_key
    assert result.created_storage_keys == (destination_key,)


async def test_new_batch_is_flushed_before_its_distributed_documents() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger = SimpleNamespace(id=uuid.uuid4())
    events: list[str] = []
    session = MagicMock()
    session.add = MagicMock(side_effect=lambda model: events.append(f"add:{type(model).__name__}"))
    session.flush = AsyncMock(
        side_effect=lambda objects=None: events.append(
            "flush:batch" if objects is not None else "flush:all"
        )
    )
    matcher = MagicMock()
    matcher.classify.return_value = ClassifiedDocument(
        original_filename="visa.pdf",
        detected_type="visa",
        accepted=True,
        reason="Accepted",
        text="",
        extracted_name="Asha Mehta",
        extracted_passport_number="P1234567",
        extracted_reference="EV123456",
    )
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    audit_repository = MagicMock()

    async def record_audit(**_kwargs) -> None:
        events.append("audit")

    audit_repository.record = AsyncMock(side_effect=record_audit)

    with patch(
        "app.infrastructure.documents.distribution_ingestion.AuditLogRepository",
        return_value=audit_repository,
    ):
        await TravelDocumentIngestionService(
            session,
            matcher=matcher,
            storage=storage,
        ).ingest(
            agency_id=agency_id,
            group_id=group_id,
            document_type="visa",
            passengers=[passenger],
            files=[TravelDocumentFile(filename="visa.pdf", content=b"%PDF visa")],
            created_by_user_id=None,
            actor_email=None,
            forced_passenger_id=passenger.id,
        )

    assert events == [
        "add:DocumentDistributionBatchModel",
        "flush:batch",
        "add:DistributedDocumentModel",
        "audit",
        "flush:all",
    ]


async def test_rejected_claim_form_is_never_uploaded_or_persisted_as_a_document(
    monkeypatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger = SimpleNamespace(id=uuid.uuid4())
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    storage.delete_files = AsyncMock(return_value=0)
    matcher = DocumentMatcher()
    monkeypatch.setattr(
        matcher,
        "_pdf_text",
        lambda _content: (
            "TRAVEL INSURANCE CLAIM FORM INVOICE Ticket number: Flight number: Departure: Arrival:"
        ),
    )
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
            document_type="flight_ticket",
            passengers=[passenger],
            files=[TravelDocumentFile(filename="claim.pdf", content=b"%PDF-1.7 claim")],
            created_by_user_id=None,
            actor_email=None,
            forced_passenger_id=passenger.id,
        )

    storage.upload_file.assert_not_awaited()
    assert result.documents == []
    assert result.batch.rejected_count == 1
    assert result.created_storage_keys == ()


async def test_precommit_persistence_failure_cleans_owned_storage_keys() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger = SimpleNamespace(id=uuid.uuid4())
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock(side_effect=[None, RuntimeError("constraint failure")])
    session.rollback = AsyncMock()
    matcher = MagicMock()
    matcher.classify.return_value = ClassifiedDocument(
        original_filename="visa.pdf",
        detected_type="visa",
        accepted=True,
        reason="Accepted",
        text="",
        extracted_name="Asha Mehta",
        extracted_passport_number="P1234567",
        extracted_reference=None,
    )
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    storage.delete_files = AsyncMock(return_value=1)
    audit_repository = MagicMock()
    audit_repository.record = AsyncMock()

    with (
        patch(
            "app.infrastructure.documents.distribution_ingestion.AuditLogRepository",
            return_value=audit_repository,
        ),
        pytest.raises(RuntimeError, match="constraint failure"),
    ):
        await TravelDocumentIngestionService(
            session,
            matcher=matcher,
            storage=storage,
        ).ingest(
            agency_id=agency_id,
            group_id=group_id,
            document_type="visa",
            passengers=[passenger],
            files=[TravelDocumentFile(filename="visa.pdf", content=b"%PDF visa")],
            created_by_user_id=None,
            actor_email=None,
            forced_passenger_id=passenger.id,
        )

    storage.delete_files.assert_awaited_once()
    assert len(storage.delete_files.await_args.args[0]) == 1
    session.rollback.assert_awaited_once()


async def test_storage_finishes_before_reauthorization_and_database_staging() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger = SimpleNamespace(id=uuid.uuid4())
    events: list[str] = []
    session = MagicMock()
    session.add = MagicMock(side_effect=lambda _row: events.append("db-stage"))
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    matcher = MagicMock()
    matcher.classify.return_value = ClassifiedDocument(
        original_filename="visa.pdf",
        detected_type="visa",
        accepted=True,
        reason="Accepted",
        text="",
        extracted_name="Asha Mehta",
        extracted_passport_number="P1234567",
        extracted_reference=None,
    )
    storage = MagicMock()
    storage.upload_file = AsyncMock(side_effect=lambda *_args: events.append("upload"))
    storage.delete_files = AsyncMock(return_value=0)
    audit_repository = MagicMock()
    audit_repository.record = AsyncMock()

    async def reauthorize():
        events.append("reauthorize")
        return uuid.uuid4(), "current@example.test"

    async def enforce_capacity(incoming_rows: int):
        assert incoming_rows == 1
        events.append("capacity")

    with patch(
        "app.infrastructure.documents.distribution_ingestion.AuditLogRepository",
        return_value=audit_repository,
    ):
        await TravelDocumentIngestionService(
            session,
            matcher=matcher,
            storage=storage,
        ).ingest(
            agency_id=agency_id,
            group_id=group_id,
            document_type="visa",
            passengers=[passenger],
            files=[TravelDocumentFile(filename="visa.pdf", content=b"%PDF visa")],
            created_by_user_id=None,
            actor_email=None,
            forced_passenger_id=passenger.id,
            before_persistence=reauthorize,
            before_persistence_capacity=enforce_capacity,
        )

    assert events.index("upload") < events.index("reauthorize")
    assert events.index("reauthorize") < events.index("capacity")
    assert events.index("capacity") < events.index("db-stage")


async def test_reauthorization_failure_rolls_back_and_cleans_uploaded_objects() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger = SimpleNamespace(id=uuid.uuid4())
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    matcher = MagicMock()
    matcher.classify.return_value = ClassifiedDocument(
        original_filename="visa.pdf",
        detected_type="visa",
        accepted=True,
        reason="Accepted",
        text="",
        extracted_name="Asha Mehta",
        extracted_passport_number="P1234567",
        extracted_reference=None,
    )
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    storage.delete_files = AsyncMock(return_value=1)

    async def reject_authorization():
        raise RuntimeError("authorization changed")

    with pytest.raises(RuntimeError, match="authorization changed"):
        await TravelDocumentIngestionService(
            session,
            matcher=matcher,
            storage=storage,
        ).ingest(
            agency_id=agency_id,
            group_id=group_id,
            document_type="visa",
            passengers=[passenger],
            files=[TravelDocumentFile(filename="visa.pdf", content=b"%PDF visa")],
            created_by_user_id=None,
            actor_email=None,
            forced_passenger_id=passenger.id,
            before_persistence=reject_authorization,
        )

    storage.upload_file.assert_awaited_once()
    storage.delete_files.assert_awaited_once()
    session.rollback.assert_awaited_once()
    session.add.assert_not_called()


async def test_capacity_failure_rolls_back_and_cleans_before_database_staging() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger = SimpleNamespace(id=uuid.uuid4())
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    matcher = MagicMock()
    matcher.classify.return_value = ClassifiedDocument(
        original_filename="visa.pdf",
        detected_type="visa",
        accepted=True,
        reason="Accepted",
        text="",
        extracted_name="Asha Mehta",
        extracted_passport_number="P1234567",
        extracted_reference=None,
    )
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    storage.delete_files = AsyncMock(return_value=1)
    reauthorize = AsyncMock(return_value=(uuid.uuid4(), "current@example.test"))

    async def reject_capacity(incoming_rows: int):
        assert incoming_rows == 1
        raise DocumentDistributionCapacityError(scope="group_document_type")

    with pytest.raises(DocumentDistributionCapacityError):
        await TravelDocumentIngestionService(
            session,
            matcher=matcher,
            storage=storage,
        ).ingest(
            agency_id=agency_id,
            group_id=group_id,
            document_type="visa",
            passengers=[passenger],
            files=[TravelDocumentFile(filename="visa.pdf", content=b"%PDF visa")],
            created_by_user_id=None,
            actor_email=None,
            forced_passenger_id=passenger.id,
            before_persistence=reauthorize,
            before_persistence_capacity=reject_capacity,
        )

    reauthorize.assert_awaited_once()
    storage.upload_file.assert_awaited_once()
    storage.delete_files.assert_awaited_once()
    session.rollback.assert_awaited_once()
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


async def test_ambiguous_upload_failure_cleans_the_preclaimed_storage_key() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger = SimpleNamespace(id=uuid.uuid4())
    session = MagicMock()
    session.add = MagicMock()
    matcher = MagicMock()
    matcher.classify.return_value = ClassifiedDocument(
        original_filename="visa.pdf",
        detected_type="visa",
        accepted=True,
        reason="Accepted",
        text="",
        extracted_name="Asha Mehta",
        extracted_passport_number="P1234567",
        extracted_reference=None,
    )
    storage = MagicMock()
    storage.upload_file = AsyncMock(side_effect=RuntimeError("upload acknowledgement lost"))
    storage.delete_files = AsyncMock(return_value=1)

    with pytest.raises(RuntimeError, match="acknowledgement lost"):
        await TravelDocumentIngestionService(
            session,
            matcher=matcher,
            storage=storage,
        ).ingest(
            agency_id=agency_id,
            group_id=group_id,
            document_type="visa",
            passengers=[passenger],
            files=[TravelDocumentFile(filename="visa.pdf", content=b"%PDF visa")],
            created_by_user_id=None,
            actor_email=None,
            forced_passenger_id=passenger.id,
        )

    storage.delete_files.assert_awaited_once()
    claimed_keys = storage.delete_files.await_args.args[0]
    assert len(claimed_keys) == 1
    assert claimed_keys[0].startswith(f"document-distribution/{group_id}/")
    session.add.assert_not_called()


async def test_one_combined_pdf_may_assign_all_1500_passengers() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger_ids = [uuid.uuid4() for _ in range(1_500)]
    passengers = [SimpleNamespace(id=passenger_id) for passenger_id in passenger_ids]
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    matcher = MagicMock()
    matcher.classify.return_value = _accepted_combined_document()
    matcher.build_index.return_value = MagicMock()
    matcher.match_all.return_value = _matched_passengers(passenger_ids)
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
            passengers=passengers,
            files=[TravelDocumentFile(filename="combined.pdf", content=b"%PDF combined")],
            created_by_user_id=None,
            actor_email=None,
            require_passenger_match=True,
        )

    assert len(result.documents) == 1_500
    assert result.batch.uploaded_count == 1_500
    assert result.batch.matched_count == 1_500
    storage.upload_file.assert_awaited_once()
    assert session.flush.await_count == 2


async def test_multi_pdf_amplification_is_rejected_before_storage_or_database_writes() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger_ids = [uuid.uuid4() for _ in range(1_500)]
    passengers = [SimpleNamespace(id=passenger_id) for passenger_id in passenger_ids]
    matches = _matched_passengers(passenger_ids)
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    matcher = MagicMock()
    matcher.classify.return_value = _accepted_combined_document()
    matcher.build_index.return_value = MagicMock()
    matcher.match_all.return_value = matches
    storage = MagicMock()
    storage.upload_file = AsyncMock()

    with pytest.raises(DocumentDistributionCapacityError) as exc_info:
        await TravelDocumentIngestionService(
            session,
            matcher=matcher,
            storage=storage,
        ).ingest(
            agency_id=agency_id,
            group_id=group_id,
            document_type="visa",
            passengers=passengers,
            files=[
                TravelDocumentFile(
                    filename=f"combined-{file_index}.pdf",
                    content=b"%PDF combined",
                )
                for file_index in range(25)
            ],
            created_by_user_id=None,
            actor_email=None,
        )

    assert exc_info.value.limit == 3_000
    assert str(exc_info.value) == (
        "This upload would create more than 3,000 document assignments in one batch. "
        "Upload fewer combined PDFs at a time."
    )
    # Two 1,500-row combined PDFs fill the budget. The third fails immediately;
    # the remaining 22 PDFs are never expanded into assignment candidates.
    assert matcher.match_all.call_count == 3
    storage.upload_file.assert_not_awaited()
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


async def test_existing_batch_assignment_rows_count_toward_capacity() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger_ids = [uuid.uuid4(), uuid.uuid4()]
    passengers = [SimpleNamespace(id=passenger_id) for passenger_id in passenger_ids]
    existing_batch = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=group_id,
        document_type="visa",
        uploaded_count=2_999,
    )
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    matcher = MagicMock()
    matcher.classify.return_value = _accepted_combined_document()
    matcher.build_index.return_value = MagicMock()
    matcher.match_all.return_value = _matched_passengers(passenger_ids)
    storage = MagicMock()
    storage.upload_file = AsyncMock()

    with pytest.raises(DocumentDistributionCapacityError):
        await TravelDocumentIngestionService(
            session,
            matcher=matcher,
            storage=storage,
        ).ingest(
            agency_id=agency_id,
            group_id=group_id,
            document_type="visa",
            passengers=passengers,
            files=[TravelDocumentFile(filename="combined.pdf", content=b"%PDF combined")],
            created_by_user_id=None,
            actor_email=None,
            existing_batch=existing_batch,
        )

    storage.upload_file.assert_not_awaited()
    session.add.assert_not_called()
    session.flush.assert_not_awaited()
