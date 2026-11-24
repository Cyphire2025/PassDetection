"""Small, isolated persisted email graph for ORM ownership and deferral tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailArtifactDocumentModel,
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailOAuthStateModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    UserModel,
)


async def persist_email_model_graph(session):
    agency = AgencyModel(id=uuid.uuid4(), name="Synthetic email agency", email="agency@example.test")
    users = [UserModel(id=uuid.uuid4(), agency_id=agency.id, email=f"owner-{i}@example.test",
                       full_name=f"Synthetic owner {i}", hashed_password="unused-test-hash", role="admin")
             for i in range(2)]
    session.add(agency)
    await session.flush()
    session.add_all(users)
    await session.flush()
    common = dict(agency_id=agency.id, owner_user_id=users[0].id)
    connection = EmailConnectionModel(id=uuid.uuid4(), **common, provider="gmail",
        provider_account_id="synthetic-mailbox", email_address=" Owner@Example.TEST ",
        access_token_ciphertext=b"opaque-test-access", refresh_token_ciphertext=b"opaque-test-refresh")
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Synthetic email group", token=uuid.uuid4().hex)
    session.add_all([connection, group])
    await session.flush()
    message = EmailMessageModel(id=uuid.uuid4(), **common, connection_id=connection.id,
        provider_message_id="synthetic-message", received_at=datetime.now(UTC))
    batch = DocumentDistributionBatchModel(id=uuid.uuid4(), agency_id=agency.id,
        group_id=group.id, document_type="visa")
    session.add_all([message, batch])
    await session.flush()
    artifact = EmailArtifactModel(id=uuid.uuid4(), **common, message_id=message.id,
        provider_artifact_id="synthetic-artifact", kind="attachment",
        source_url_ciphertext=b"opaque-test-url", source_url_encryption_key_version=1)
    document = DistributedDocumentModel(id=uuid.uuid4(), agency_id=agency.id,
        group_id=group.id, batch_id=batch.id, document_type="visa",
        original_filename="synthetic.pdf", storage_key="tests/synthetic.pdf")
    review = EmailReviewItemModel(id=uuid.uuid4(), **common, message_id=message.id,
        review_type="processing_failure", proposed_action="retry")
    session.add_all([artifact, document, review])
    await session.flush()
    link = EmailArtifactDocumentModel(id=uuid.uuid4(), **common, artifact_id=artifact.id,
        distributed_document_id=document.id, result_type="created")
    activity = EmailActivityEventModel(id=uuid.uuid4(), **common, connection_id=connection.id,
        message_id=message.id, artifact_id=artifact.id, review_item_id=review.id,
        event_key="synthetic-event", event_type="discovered", stage="info", summary_code="discovered")
    oauth = EmailOAuthStateModel(id=uuid.uuid4(), agency_id=agency.id, user_id=users[0].id,
        connection_id=connection.id, provider="gmail", state_hash="1" * 64,
        code_verifier_ciphertext=b"opaque-test-verifier", expires_at=datetime.now(UTC) + timedelta(minutes=10))
    session.add_all([link, activity, oauth])
    await session.commit()
    return SimpleNamespace(agency_id=agency.id, owner_id=users[0].id, other_owner_id=users[1].id,
        connection=connection, message=message, artifact=artifact, link=link,
        review=review, activity=activity, oauth=oauth)
