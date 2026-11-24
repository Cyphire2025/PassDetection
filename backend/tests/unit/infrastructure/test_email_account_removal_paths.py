"""Actual sparse/sole-batch/shared-key removal outcomes through the public helper."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.infrastructure.database.email_models import (
    EmailArtifactDocumentModel,
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
    NotificationModel,
    UserModel,
)
from app.infrastructure.email.account_removal import purge_email_connection_records


@pytest.fixture
async def mailbox(db_session):
    agency = AgencyModel(id=uuid.uuid4(), name="Synthetic", email="agency@example.test")
    db_session.add(agency)
    await db_session.flush()
    owner = UserModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        email="owner@example.test",
        full_name="Owner",
        hashed_password="unused",
        role="agency_staff",
    )
    db_session.add(owner)
    await db_session.flush()
    connection = EmailConnectionModel(
        agency_id=agency.id,
        owner_user_id=owner.id,
        provider="gmail",
        provider_account_id="synthetic-account",
        email_address=owner.email,
        created_by_user_id=owner.id,
    )
    db_session.add(connection)
    await db_session.commit()
    return SimpleNamespace(agency=agency, owner=owner, connection=connection)


async def _message(session, connection, suffix):
    message = EmailMessageModel(
        agency_id=connection.agency_id,
        owner_user_id=connection.owner_user_id,
        connection_id=connection.id,
        provider_message_id=suffix,
        sender_address="supplier@example.test",
        subject="Synthetic operational message",
        received_at=datetime.now(UTC),
    )
    session.add(message)
    await session.flush()
    return message


async def _artifact(session, message, key):
    artifact = EmailArtifactModel(
        agency_id=message.agency_id,
        owner_user_id=message.owner_user_id,
        message_id=message.id,
        provider_artifact_id="synthetic-attachment",
        kind="attachment",
        storage_key=key,
    )
    session.add(artifact)
    await session.flush()
    return artifact


async def test_empty_connection_removal_keeps_commit_ownership_and_can_rollback(
    db_session, mailbox
):
    connection_id = mailbox.connection.id
    committed = []

    def listener(_session):
        committed.append(True)

    event.listen(db_session.sync_session, "after_commit", listener)
    try:
        result = await purge_email_connection_records(db_session, connection=mailbox.connection)
        assert result.connection_id == connection_id
        assert result.message_count == result.artifact_count == result.document_count == 0
        assert result.activity_count == result.notification_count == result.audit_log_count == 0
        assert result.storage_keys == () and committed == []
        assert await db_session.get(EmailConnectionModel, connection_id) is None
        await db_session.rollback()
        assert await db_session.get(EmailConnectionModel, connection_id) is not None
    finally:
        event.remove(db_session.sync_session, "after_commit", listener)


async def test_message_without_artifacts_removes_only_its_operational_notification(
    db_session, mailbox
):
    message = await _message(db_session, mailbox.connection, "message-only")
    matching = NotificationModel(
        agency_id=mailbox.agency.id,
        user_id=mailbox.owner.id,
        type="email_ai",
        title="Synthetic",
        message="Synthetic",
        category="email_operations",
        entity_type="email_message",
        entity_id=str(message.id),
    )
    retained = NotificationModel(
        agency_id=mailbox.agency.id,
        user_id=mailbox.owner.id,
        type="other",
        title="Retained",
        message="Retained",
        category="other",
        entity_type="email_message",
        entity_id=str(message.id),
    )
    db_session.add_all([matching, retained])
    await db_session.flush()
    matching_id, retained_id = matching.id, retained.id

    result = await purge_email_connection_records(db_session, connection=mailbox.connection)

    assert result.message_count == 1 and result.artifact_count == 0
    assert result.notification_count == 1 and result.storage_keys == ()
    assert await db_session.get(NotificationModel, matching_id) is None
    assert await db_session.get(NotificationModel, retained_id) is retained


async def test_pending_artifact_without_a_storage_object_still_removes_relational_rows(
    db_session, mailbox
):
    message = await _message(db_session, mailbox.connection, "pending-artifact")
    artifact = await _artifact(db_session, message, None)
    artifact_id = artifact.id
    result = await purge_email_connection_records(db_session, connection=mailbox.connection)
    assert result.message_count == result.artifact_count == 1
    assert result.document_count == 0 and result.storage_keys == ()
    assert await db_session.get(EmailArtifactModel, artifact_id) is None


@pytest.mark.parametrize("shared_key", [None, "artifact", "document"])
async def test_sole_batch_cleanup_preserves_other_object_references_and_detaches_delivery(
    db_session, mailbox, shared_key
):
    message = await _message(db_session, mailbox.connection, "sole-document")
    artifact = await _artifact(db_session, message, "synthetic/staged.pdf")
    group = ClientGroupModel(
        agency_id=mailbox.agency.id,
        name="Synthetic group",
        token=f"synthetic-{uuid.uuid4()}",
        created_by_user_id=mailbox.owner.id,
    )
    db_session.add(group)
    await db_session.flush()
    batch = DocumentDistributionBatchModel(
        agency_id=mailbox.agency.id,
        group_id=group.id,
        document_type="visa",
        status="saved",
        created_by_user_id=mailbox.owner.id,
    )
    db_session.add(batch)
    await db_session.flush()
    document = DistributedDocumentModel(
        batch_id=batch.id,
        agency_id=mailbox.agency.id,
        group_id=group.id,
        document_type="visa",
        original_filename="sole.pdf",
        storage_key="synthetic/canonical.pdf",
    )
    db_session.add(document)
    await db_session.flush()
    db_session.add(
        EmailArtifactDocumentModel(
            agency_id=mailbox.agency.id,
            owner_user_id=mailbox.owner.id,
            artifact_id=artifact.id,
            distributed_document_id=document.id,
            result_type="created",
        )
    )
    delivery = DocumentWhatsAppDeliveryModel(
        agency_id=mailbox.agency.id,
        group_id=group.id,
        document_batch_id=batch.id,
        distributed_document_id=None,
        send_batch_id=uuid.uuid4(),
        document_type="visa",
        document_filename="sole.pdf",
        passenger_name="Synthetic passenger",
        phone_number="+00000000000",
        normalized_phone_number="00000000000",
        template_name="unused",
        status="queued",
    )
    db_session.add(delivery)
    await db_session.flush()
    if shared_key == "artifact":
        other = EmailConnectionModel(
            agency_id=mailbox.agency.id,
            owner_user_id=mailbox.owner.id,
            provider="outlook",
            provider_account_id="other-account",
            email_address="other@example.test",
        )
        db_session.add(other)
        await db_session.flush()
        other_message = await _message(db_session, other, "retained-message")
        await _artifact(db_session, other_message, "synthetic/staged.pdf")
    elif shared_key == "document":
        other_batch = DocumentDistributionBatchModel(
            agency_id=mailbox.agency.id, group_id=group.id, document_type="visa", status="saved"
        )
        db_session.add(other_batch)
        await db_session.flush()
        db_session.add(
            DistributedDocumentModel(
                batch_id=other_batch.id,
                agency_id=mailbox.agency.id,
                group_id=group.id,
                document_type="visa",
                original_filename="manual.pdf",
                storage_key="synthetic/canonical.pdf",
            )
        )
    await db_session.flush()
    batch_id, document_id = batch.id, document.id

    result = await purge_email_connection_records(db_session, connection=mailbox.connection)

    assert result.document_count == 1
    assert await db_session.get(DistributedDocumentModel, document_id) is None
    assert await db_session.get(DocumentDistributionBatchModel, batch_id) is None
    await db_session.refresh(delivery)
    assert delivery.document_batch_id is None
    expected = {"synthetic/staged.pdf", "synthetic/canonical.pdf"}
    if shared_key:
        expected.remove(
            "synthetic/staged.pdf" if shared_key == "artifact" else "synthetic/canonical.pdf"
        )
    assert set(result.storage_keys) == expected
