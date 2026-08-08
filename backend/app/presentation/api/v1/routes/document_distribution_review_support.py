"""Deterministic match snapshots and review helpers for document distribution."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Literal

from app.domain.entities.entities import (
    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES,
    PassportSubmission,
    User,
    UserRole,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    DistributedDocumentModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.export.document_assignment_excel_exporter import (
    DocumentAssignmentExportRow,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DistributedDocumentResponse,
    DocumentAssignmentIssueResponse,
    DocumentPassengerReviewRow,
)


def _owner_scope_for(user: User) -> uuid.UUID | None:
    return user.id if user.role == UserRole.AGENCY_STAFF else None


def _submitted_statuses() -> tuple[str, ...]:
    return OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES


def _passport_number(passenger: PassportSubmission) -> str | None:
    fields = passenger.confirmed_fields or passenger.extracted_fields or {}
    value = fields.get("passport_number")
    return str(value).strip() if value else None


def _safe_filename(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())[:120]
    return name or "document.pdf"


DocumentAssignmentExportFilter = Literal[
    "all",
    "assigned",
    "missing",
    "sent",
    "not_sent",
]
_SENT_DOCUMENT_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})


def _joined_document_values(values: list[object]) -> str:
    return "\n".join(dict.fromkeys(str(value).strip() for value in values if value))


def _document_assignment_export_rows(
    rows: list[DocumentPassengerReviewRow],
    *,
    review_filter: DocumentAssignmentExportFilter,
    search_query: str,
) -> list[DocumentAssignmentExportRow]:
    normalized_search = search_query.strip().casefold()
    export_rows: list[DocumentAssignmentExportRow] = []
    for row in rows:
        if normalized_search and normalized_search not in row.passenger_name.casefold():
            continue
        documents = row.documents or ([row.document] if row.document is not None else [])
        assigned = bool(documents)
        sent = any(document.delivery_status in _SENT_DOCUMENT_STATUSES for document in documents)
        not_sent = any(
            document.delivery_status not in _SENT_DOCUMENT_STATUSES for document in documents
        )
        if review_filter == "assigned" and not assigned:
            continue
        if review_filter == "missing" and assigned:
            continue
        if review_filter == "sent" and not sent:
            continue
        if review_filter == "not_sent" and not not_sent:
            continue

        export_rows.append(
            DocumentAssignmentExportRow(
                passenger_name=row.passenger_name,
                passport_number=row.passport_number or "",
                departure_city=row.departure_city or "",
                assignment_status="Assigned" if assigned else "Missing",
                document_count=len(documents),
                document_filenames=_joined_document_values(
                    [document.original_filename for document in documents]
                ),
                match_statuses=_joined_document_values(
                    [document.match_status for document in documents]
                ),
                match_confidences=_joined_document_values(
                    [f"{document.match_confidence:.0%}" for document in documents]
                ),
                delivery_statuses=_joined_document_values(
                    [document.delivery_status for document in documents]
                ),
                sent_to=_joined_document_values([document.sent_to for document in documents]),
                last_sent_at=_joined_document_values(
                    [document.last_sent_at for document in documents]
                ),
                match_reasons=_joined_document_values(
                    [document.match_reason for document in documents]
                ),
            )
        )
    return export_rows


@dataclass(frozen=True)
class _LinkedDocumentMatchSource:
    """A canonical view of every linked row that can influence assignment."""

    linked_broadcasts: dict[uuid.UUID, str]
    recipients: tuple[WhatsAppBroadcastRecipientModel, ...]
    snapshot: tuple[tuple[str, ...], ...]


def _snapshot_value(value: object) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _linked_document_match_source_from_models(
    *,
    group: ClientGroupModel,
    links: list[ClientGroupWhatsAppBroadcastLinkModel],
    broadcasts: list[WhatsAppBroadcastGroupModel],
    recipients: list[WhatsAppBroadcastRecipientModel],
) -> _LinkedDocumentMatchSource:
    """Build a deterministic, tenant-scoped snapshot from one coherent row set."""

    linked_broadcasts = {
        broadcast.id: broadcast.name
        for broadcast in broadcasts
        if broadcast.agency_id == group.agency_id
    }
    scoped_links = sorted(
        (
            link
            for link in links
            if link.agency_id == group.agency_id
            and link.client_group_id == group.id
            and link.broadcast_group_id in linked_broadcasts
        ),
        key=lambda item: str(item.id),
    )
    scoped_recipients = sorted(
        (
            recipient
            for recipient in recipients
            if recipient.agency_id == group.agency_id
            and recipient.broadcast_group_id in linked_broadcasts
            and recipient.removed_at is None
        ),
        key=lambda item: str(item.id),
    )
    snapshot: list[tuple[str, ...]] = []
    for link in scoped_links:
        snapshot.append(
            (
                "link",
                str(link.id),
                str(link.client_group_id),
                str(link.broadcast_group_id),
                str(link.agency_id),
                str(link.created_by_user_id or ""),
                _snapshot_value(link.created_at),
            )
        )
    for broadcast in sorted(broadcasts, key=lambda item: str(item.id)):
        if broadcast.id not in linked_broadcasts:
            continue
        snapshot.append(
            (
                "broadcast",
                str(broadcast.id),
                str(broadcast.agency_id),
                str(broadcast.name or ""),
            )
        )
    for recipient in scoped_recipients:
        snapshot.append(
            (
                "recipient",
                str(recipient.id),
                str(recipient.broadcast_group_id),
                str(recipient.agency_id),
                str(recipient.name or ""),
                str(recipient.normalized_phone_number or ""),
                _snapshot_value(recipient.created_at),
                json.dumps(
                    dict(recipient.imported_fields or {}),
                    sort_keys=True,
                    default=str,
                    separators=(",", ":"),
                ),
            )
        )
    return _LinkedDocumentMatchSource(
        linked_broadcasts=linked_broadcasts,
        recipients=tuple(scoped_recipients),
        snapshot=tuple(snapshot),
    )


def _document_match_roster_snapshot(
    passengers: list[PassportSubmission],
) -> tuple[tuple[str, ...], ...]:
    """Capture every passenger field that can influence document assignment."""

    snapshots: list[tuple[str, ...]] = []
    for passenger in passengers:
        updated_at = getattr(passenger, "updated_at", None)
        snapshots.append(
            (
                str(passenger.id),
                updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at),
                str(getattr(passenger, "client_name", "") or ""),
                str(getattr(passenger, "client_phone", "") or ""),
                str(getattr(passenger, "family_head_phone", "") or ""),
                json.dumps(
                    {
                        "confirmed_fields": getattr(passenger, "confirmed_fields", None) or {},
                        "extracted_fields": getattr(passenger, "extracted_fields", None) or {},
                        "staff_metadata": getattr(passenger, "staff_metadata", None) or {},
                        "custom_answers": getattr(passenger, "custom_answers", None) or [],
                        "custom_detail_answers": (
                            getattr(passenger, "custom_detail_answers", None) or []
                        ),
                    },
                    sort_keys=True,
                    default=str,
                    separators=(",", ":"),
                ),
            )
        )
    return tuple(sorted(snapshots))


def _passenger_review_rows(
    *,
    passengers: list[PassportSubmission],
    documents: list[DistributedDocumentModel],
    responses_by_document: dict[uuid.UUID, DistributedDocumentResponse],
) -> tuple[
    list[DocumentPassengerReviewRow],
    list[DistributedDocumentResponse],
    int,
]:
    """Group the persistent document ledger into one row per submitted passenger."""

    passenger_ids = {passenger.id for passenger in passengers}
    docs_by_passenger: dict[uuid.UUID, list[DistributedDocumentModel]] = {}
    unmatched: list[DistributedDocumentResponse] = []
    for document in documents:
        if document.passenger_id in passenger_ids:
            docs_by_passenger.setdefault(document.passenger_id, []).append(document)
        else:
            unmatched.append(responses_by_document[document.id])

    rows: list[DocumentPassengerReviewRow] = []
    matched_passenger_count = 0
    for passenger in passengers:
        passenger_documents = docs_by_passenger.get(passenger.id, [])
        rendered_documents = [
            responses_by_document[document.id] for document in passenger_documents
        ]
        if any(document.match_status == "matched" for document in passenger_documents):
            matched_passenger_count += 1
        rows.append(
            DocumentPassengerReviewRow(
                passenger_id=passenger.id,
                passenger_name=passenger.client_name,
                passport_number=_passport_number(passenger),
                departure_city=passenger.departure_city,
                document=rendered_documents[0] if rendered_documents else None,
                documents=rendered_documents,
            )
        )

    return rows, unmatched, matched_passenger_count


def _physical_file_accounting(
    *,
    passengers: list[PassportSubmission],
    documents: list[DistributedDocumentModel],
    responses_by_document: dict[uuid.UUID, DistributedDocumentResponse],
) -> tuple[int, int, int, list[DocumentAssignmentIssueResponse]]:
    """Count stored PDFs independently from their assignment rows.

    A combined PDF can intentionally create several rows that share one
    storage key, while several PDFs can be assigned to the same passenger.
    Grouping by the server-generated storage key keeps both cases truthful.
    """

    passenger_ids = {passenger.id for passenger in passengers}
    physical_documents: dict[str, list[DistributedDocumentModel]] = {}
    for document in documents:
        storage_identity = str(getattr(document, "storage_key", "") or document.id)
        physical_documents.setdefault(storage_identity, []).append(document)

    assigned_files = 0
    assigned_passengers: set[uuid.UUID] = set()
    issues: list[DocumentAssignmentIssueResponse] = []
    for grouped_documents in physical_documents.values():
        valid_assignments = [
            document
            for document in grouped_documents
            if document.match_status == "matched" and document.passenger_id in passenger_ids
        ]
        if valid_assignments:
            assigned_files += 1
            assigned_passengers.update(
                document.passenger_id
                for document in valid_assignments
                if document.passenger_id is not None
            )
            continue

        representative = grouped_documents[0]
        response = responses_by_document[representative.id]
        if any(
            document.passenger_id is not None and document.passenger_id not in passenger_ids
            for document in grouped_documents
        ):
            code = "passenger_no_longer_in_group"
            reason = "The previously matched passenger is no longer in this group."
        elif any(document.match_status == "duplicate_document" for document in grouped_documents):
            code = "duplicate_document"
            reason = response.match_reason or "This PDF duplicates an existing saved document."
        else:
            code = "no_unique_passenger_match"
            reason = response.match_reason or "No unique passenger match was found."
        issues.append(
            DocumentAssignmentIssueResponse(
                document_id=response.id,
                original_filename=response.original_filename,
                code=code,
                reason=reason,
                url=response.url,
            )
        )

    return len(physical_documents), assigned_files, len(assigned_passengers), issues
