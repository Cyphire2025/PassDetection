"""Synthetic persisted assignment scope; storage/provider work stays isolated."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.documents.document_approval_provenance import (
    MANUAL_DOCUMENT_TYPE_APPROVAL_PREFIX,
)
from tests.persistence import persist_graph

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


@dataclass(frozen=True)
class AssignmentGraph:
    actor: User
    group: ClientGroupModel
    passenger: PassportSubmissionModel
    batch: DocumentDistributionBatchModel
    document: DistributedDocumentModel
    unmatched: DistributedDocumentModel


async def persist_assignment_graph(session: AsyncSession) -> AssignmentGraph:
    agency_id, actor_id, group_id, passenger_id, batch_id = (uuid.uuid4() for _ in range(5))
    actor = User(
        id=actor_id,
        agency_id=agency_id,
        email="assignment@example.test",
        full_name="Assignment operator",
        hashed_password="unused",
        role=UserRole.AGENCY_ADMIN,
    )
    group = ClientGroupModel(
        id=group_id,
        agency_id=agency_id,
        name="Synthetic trip",
        token=uuid.uuid4().hex,
    )
    passenger = PassportSubmissionModel(
        id=passenger_id,
        agency_id=agency_id,
        group_id=group_id,
        client_name="Synthetic passenger",
        client_phone="+919111111111",
        client_email="passenger@example.test",
        status="staff_approved",
        image_s3_key="synthetic/passport.jpg",
        confirmed_at=NOW,
        confirmed_fields={
            "given_names": "Synthetic",
            "surname": "Passenger",
            "passport_number": "P0001",
        },
    )
    batch = DocumentDistributionBatchModel(
        id=batch_id,
        agency_id=agency_id,
        group_id=group_id,
        document_type="visa",
        status="saved",
        uploaded_count=2,
        matched_count=1,
        saved_at=NOW,
    )
    documents = [
        DistributedDocumentModel(
            id=uuid.uuid4(),
            batch_id=batch_id,
            agency_id=agency_id,
            group_id=group_id,
            passenger_id=passenger_id if assigned else None,
            document_type="visa",
            original_filename="assigned.pdf" if assigned else "unmatched.pdf",
            storage_key=f"document-distribution/{agency_id}/{group_id}/{batch_id}/{index}.pdf",
            detected_type="visa",
            match_status="matched" if assigned else "needs_review",
            match_confidence=1.0 if assigned else 0.0,
            match_reason=MANUAL_DOCUMENT_TYPE_APPROVAL_PREFIX + "Original passenger match"
            if assigned
            else "No match",
            created_at=NOW,
            updated_at=NOW,
        )
        for index, assigned in enumerate([True, False])
    ]
    await persist_graph(
        session,
        [
            AgencyModel(id=agency_id, name="Synthetic agency", email="agency@example.test"),
            UserModel(
                id=actor_id,
                agency_id=agency_id,
                email=actor.email,
                hashed_password="unused",
                full_name=actor.full_name,
                role=actor.role.value,
            ),
            group,
            passenger,
            batch,
            *documents,
        ],
    )
    await session.commit()
    return AssignmentGraph(actor, group, passenger, batch, documents[0], documents[1])


async def persist_delivery(
    session: AsyncSession,
    graph: AssignmentGraph,
    *,
    status: str,
) -> DocumentWhatsAppDeliveryModel:
    delivery = DocumentWhatsAppDeliveryModel(
        id=uuid.uuid4(),
        agency_id=graph.group.agency_id,
        group_id=graph.group.id,
        document_batch_id=graph.batch.id,
        distributed_document_id=graph.document.id,
        passenger_id=graph.passenger.id,
        send_batch_id=uuid.uuid4(),
        document_type="visa",
        document_filename=graph.document.original_filename,
        passenger_name=graph.passenger.client_name,
        phone_number="+919111111111",
        normalized_phone_number="+919111111111",
        template_name="synthetic_document",
        status=status,
        created_at=NOW,
        status_updated_at=NOW,
        provider_message_id="synthetic-provider-id" if status == "delivered" else None,
    )
    await persist_graph(session, [delivery])
    await session.commit()
    return delivery
