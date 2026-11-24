"""Synthetic persisted mailbox, staged artifact and permitted passenger for decisions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_models import (
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.email.sync_contracts import ReviewedArtifactIngestionResult
from app.presentation.api.v1.routes import email_integration_review_decisions as decisions
from app.presentation.api.v1.routes import email_review_actions


async def persist_email_review(session, monkeypatch):
    agency = AgencyModel(
        id=uuid.uuid4(), name="Synthetic review agency", email="agency@example.test"
    )
    session.add(agency)
    await session.flush()
    owner = UserModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        email="owner@example.test",
        full_name="Owner",
        role="agency_staff",
        hashed_password="unused",
    )
    session.add(owner)
    await session.flush()
    connection = EmailConnectionModel(
        agency_id=agency.id,
        owner_user_id=owner.id,
        provider="gmail",
        provider_account_id="synthetic-account",
        email_address=owner.email,
        status="active",
    )
    group = ClientGroupModel(
        agency_id=agency.id,
        name="Synthetic group",
        token=uuid.uuid4().hex,
        created_by_user_id=owner.id,
    )
    session.add_all([connection, group])
    await session.flush()
    message = EmailMessageModel(
        agency_id=agency.id,
        owner_user_id=owner.id,
        connection_id=connection.id,
        provider_message_id="synthetic-message",
        received_at=datetime.now(UTC),
        processing_status="review_required",
    )
    passenger = PassportSubmissionModel(
        agency_id=agency.id,
        group_id=group.id,
        client_name="Synthetic passenger",
        image_s3_key="tests/synthetic-passport.jpg",
    )
    session.add_all([message, passenger])
    await session.flush()
    artifact = EmailArtifactModel(
        agency_id=agency.id,
        owner_user_id=owner.id,
        message_id=message.id,
        provider_artifact_id="synthetic-attachment",
        kind="attachment",
        storage_key="email-integrations/staged.pdf",
        detected_type="visa",
        retrieval_status="retrieved",
        processing_status="review_required",
    )
    session.add(artifact)
    await session.flush()
    review = EmailReviewItemModel(
        agency_id=agency.id,
        owner_user_id=owner.id,
        message_id=message.id,
        artifact_id=artifact.id,
        review_type="processing_failure",
        status="open",
        proposed_action="retry",
        candidate_group_id=group.id,
        candidate_passenger_id=passenger.id,
        revision=1,
    )
    session.add(review)
    await session.commit()
    settings = SimpleNamespace(email_integrations_enabled=True, email_sync_enabled=True)
    monkeypatch.setattr(decisions, "get_settings", lambda: settings)
    ingest = AsyncMock(
        return_value=ReviewedArtifactIngestionResult(
            document_ids=(),
            storage_keys=("email-integrations-canonical/synthetic.pdf",),
            duplicate=False,
        )
    )
    enqueue = Mock(return_value=True)
    storage = SimpleNamespace(delete_files=AsyncMock(return_value=1))
    monkeypatch.setattr(email_review_actions, "ingest_reviewed_artifact", ingest)
    monkeypatch.setattr(decisions, "_enqueue_connection_sync", enqueue)
    monkeypatch.setattr(decisions, "MinioStorageRepository", lambda: storage)
    return SimpleNamespace(
        agency=agency,
        owner=owner,
        connection=connection,
        group=group,
        message=message,
        passenger=passenger,
        artifact=artifact,
        review=review,
        settings=settings,
        ingest=ingest,
        enqueue=enqueue,
        storage=storage,
        user=User(
            id=owner.id,
            email=owner.email,
            full_name=owner.full_name,
            hashed_password="unused",
            role=UserRole.AGENCY_STAFF,
            agency_id=agency.id,
        ),
    )
