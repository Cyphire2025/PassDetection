from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.presentation.api.v1.routes.document_distribution import (
    _document_assignment_export_rows,
    _passenger_review_rows,
    _physical_file_accounting,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DistributedDocumentResponse,
)


def _passenger(*, passenger_id: uuid.UUID, name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=passenger_id,
        client_name=name,
        departure_city="Kochi",
        confirmed_fields={"passport_number": f"P-{name}"},
        extracted_fields={},
    )


def _document(
    *,
    document_id: uuid.UUID,
    passenger_id: uuid.UUID | None,
    status: str = "matched",
    storage_key: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=document_id,
        passenger_id=passenger_id,
        match_status=status,
        storage_key=storage_key or f"document-distribution/{document_id}",
    )


def _response(
    *,
    document_id: uuid.UUID,
    filename: str,
    source: str,
) -> DistributedDocumentResponse:
    return DistributedDocumentResponse(
        id=document_id,
        original_filename=filename,
        document_type="visa",
        detected_type="visa",
        match_status="matched",
        match_confidence=1.0,
        source=source,
    )


def test_review_rows_group_every_saved_document_under_one_submitted_passenger() -> None:
    first_passenger_id = uuid.uuid4()
    second_passenger_id = uuid.uuid4()
    stale_passenger_id = uuid.uuid4()
    newest_document_id = uuid.uuid4()
    older_document_id = uuid.uuid4()
    stale_document_id = uuid.uuid4()
    newest_document = _document(
        document_id=newest_document_id,
        passenger_id=first_passenger_id,
    )
    older_document = _document(
        document_id=older_document_id,
        passenger_id=first_passenger_id,
    )
    stale_document = _document(
        document_id=stale_document_id,
        passenger_id=stale_passenger_id,
    )
    responses = {
        newest_document_id: _response(
            document_id=newest_document_id,
            filename="latest-manual.pdf",
            source="manual",
        ),
        older_document_id: _response(
            document_id=older_document_id,
            filename="saved-from-email.pdf",
            source="email",
        ),
        stale_document_id: _response(
            document_id=stale_document_id,
            filename="stale-passenger.pdf",
            source="manual",
        ),
    }

    rows, unmatched, matched_count = _passenger_review_rows(
        passengers=[
            _passenger(passenger_id=first_passenger_id, name="First"),
            _passenger(passenger_id=second_passenger_id, name="Second"),
        ],
        documents=[newest_document, older_document, stale_document],
        responses_by_document=responses,
    )

    assert len(rows) == 2
    assert matched_count == 1
    assert rows[0].passenger_id == first_passenger_id
    assert rows[0].document == responses[newest_document_id]
    assert rows[0].documents == [
        responses[newest_document_id],
        responses[older_document_id],
    ]
    assert rows[0].assigned_pdf_count == 2
    assert rows[1].passenger_id == second_passenger_id
    assert rows[1].document is None
    assert rows[1].documents == []
    assert rows[1].assigned_pdf_count == 0
    assert unmatched == [responses[stale_document_id]]


def test_multiple_pdf_count_uses_physical_files_and_passenger_ids_and_updates_after_reassignment() -> None:
    first = _passenger(passenger_id=uuid.uuid4(), name="Same Name")
    second = _passenger(passenger_id=uuid.uuid4(), name="Same Name")
    # The first PDF has two assignment rows for the first person. It still counts once.
    documents = [
        _document(document_id=uuid.uuid4(), passenger_id=first.id, storage_key="combined.pdf"),
        _document(document_id=uuid.uuid4(), passenger_id=first.id, storage_key="combined.pdf"),
        _document(document_id=uuid.uuid4(), passenger_id=first.id, storage_key="second.pdf"),
        _document(document_id=uuid.uuid4(), passenger_id=second.id, storage_key="combined.pdf"),
        _document(document_id=uuid.uuid4(), passenger_id=second.id, status="needs_review"),
    ]
    responses = {
        document.id: _response(document_id=document.id, filename="same-name.pdf", source="manual")
        for document in documents
    }

    rows, _, _ = _passenger_review_rows(
        passengers=[first, second], documents=documents, responses_by_document=responses
    )
    assert [(row.passenger_id, row.assigned_pdf_count) for row in rows] == [
        (first.id, 2), (second.id, 1)
    ]
    exported = _document_assignment_export_rows(
        rows, review_filter="multiple_pdfs", search_query="  SAME "
    )
    assert len(exported) == 1
    assert exported[0].document_count == 2
    assert _document_assignment_export_rows(
        rows, review_filter="multiple_pdfs", search_query="not present"
    ) == []

    documents[2].passenger_id = second.id
    updated_rows, _, _ = _passenger_review_rows(
        passengers=[first, second], documents=documents, responses_by_document=responses
    )
    assert [(row.passenger_id, row.assigned_pdf_count) for row in updated_rows] == [
        (first.id, 1), (second.id, 2)
    ]
    # The existing review continues to expose every ledger row for its existing actions.
    assert len(updated_rows[0].documents) == 2
    assert len(updated_rows[1].documents) == 3


def test_physical_file_accounting_distinguishes_files_from_unique_passengers() -> None:
    passengers = [
        _passenger(passenger_id=uuid.uuid4(), name=f"Passenger {index}") for index in range(404)
    ]
    documents: list[SimpleNamespace] = []
    responses: dict[uuid.UUID, DistributedDocumentResponse] = {}
    for index in range(406):
        document_id = uuid.uuid4()
        passenger = passengers[index if index < 404 else index - 404]
        documents.append(
            _document(
                document_id=document_id,
                passenger_id=passenger.id,
                storage_key=f"document-distribution/file-{index}",
            )
        )
        responses[document_id] = _response(
            document_id=document_id,
            filename=f"visa-{index}.pdf",
            source="manual",
        )

    physical_count, assigned_file_count, assigned_passenger_count, issues = (
        _physical_file_accounting(
            passengers=passengers,
            documents=documents,
            responses_by_document=responses,
        )
    )

    assert physical_count == 406
    assert assigned_file_count == 406
    assert assigned_passenger_count == 404
    assert issues == []


def test_physical_file_accounting_lists_each_unassigned_pdf_once_with_a_reason() -> None:
    passenger = _passenger(passenger_id=uuid.uuid4(), name="Assigned")
    assigned_id = uuid.uuid4()
    unassigned_id = uuid.uuid4()
    stale_id = uuid.uuid4()
    stale_passenger_id = uuid.uuid4()
    documents = [
        _document(document_id=assigned_id, passenger_id=passenger.id),
        _document(document_id=unassigned_id, passenger_id=None, status="needs_review"),
        _document(document_id=stale_id, passenger_id=stale_passenger_id),
    ]
    responses = {
        assigned_id: _response(document_id=assigned_id, filename="assigned.pdf", source="manual"),
        unassigned_id: _response(
            document_id=unassigned_id,
            filename="no-match.pdf",
            source="manual",
        ).model_copy(update={"match_reason": "No passenger match found"}),
        stale_id: _response(document_id=stale_id, filename="stale.pdf", source="manual"),
    }

    physical_count, assigned_file_count, assigned_passenger_count, issues = (
        _physical_file_accounting(
            passengers=[passenger],
            documents=documents,
            responses_by_document=responses,
        )
    )

    assert (physical_count, assigned_file_count, assigned_passenger_count) == (3, 1, 1)
    assert [(issue.original_filename, issue.code, issue.reason) for issue in issues] == [
        ("no-match.pdf", "no_unique_passenger_match", "No passenger match found"),
        (
            "stale.pdf",
            "passenger_no_longer_in_group",
            "The previously matched passenger is no longer in this group.",
        ),
    ]
