from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.email_ai_models import (
    EmailAiAnalysisModel,
    EmailAiFeedbackModel,
)
from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailArtifactDocumentModel,
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    NotificationModel,
    UserModel,
)
from app.infrastructure.email.account_removal import purge_email_connection_records


@pytest.mark.asyncio
async def test_account_removal_isolates_other_mailboxes_and_shared_documents(
    db_session: AsyncSession,
) -> None:
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    agency = AgencyModel(
        id=agency_id,
        name="Removal Test Agency",
        email="removal-agency@example.test",
        is_active=True,
    )
    owner = UserModel(
        id=owner_id,
        agency_id=agency_id,
        email="owner@example.test",
        hashed_password="not-used",
        full_name="Mailbox Owner",
        role="agency_admin",
        is_active=True,
    )
    db_session.add_all([agency, owner])
    await db_session.flush()

    removed_connection = EmailConnectionModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        provider="gmail",
        provider_account_id="removed-provider",
        email_address="remove@example.test",
        status="active",
        created_by_user_id=owner_id,
    )
    retained_connection = EmailConnectionModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        provider="outlook",
        provider_account_id="retained-provider",
        email_address="retain@example.test",
        status="active",
        created_by_user_id=owner_id,
    )
    db_session.add_all([removed_connection, retained_connection])
    await db_session.flush()

    removed_message = EmailMessageModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=removed_connection.id,
        provider_message_id="removed-message",
        sender_address="supplier@example.test",
        subject="Removed mailbox message",
        received_at=datetime.now(tz=UTC),
    )
    retained_message = EmailMessageModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=retained_connection.id,
        provider_message_id="retained-message",
        sender_address="supplier@example.test",
        subject="Retained mailbox message",
        received_at=datetime.now(tz=UTC),
    )
    db_session.add_all([removed_message, retained_message])
    await db_session.flush()

    analysis = EmailAiAnalysisModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=removed_connection.id,
        message_id=removed_message.id,
        status="completed",
        input_hash="a" * 64,
        prompt_schema_version="test-v1",
        config_version="test-v1",
        ai_model="test-model",
    )
    db_session.add(analysis)
    await db_session.flush()
    feedback = EmailAiFeedbackModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=removed_connection.id,
        message_id=removed_message.id,
        analysis_id=analysis.id,
        feedback_type="confirmation",
        field_name="summary",
        created_by_user_id=owner_id,
    )
    db_session.add(feedback)

    removed_artifact = EmailArtifactModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        message_id=removed_message.id,
        provider_artifact_id="removed-artifact",
        kind="attachment",
        storage_key="email-integrations/removed/staged.pdf",
        retrieval_status="retrieved",
        processing_status="completed",
        detected_type="visa",
    )
    retained_artifact = EmailArtifactModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        message_id=retained_message.id,
        provider_artifact_id="retained-artifact",
        kind="attachment",
        storage_key="email-integrations/retained/staged.pdf",
        retrieval_status="retrieved",
        processing_status="duplicate",
        detected_type="visa",
    )
    db_session.add_all([removed_artifact, retained_artifact])
    await db_session.flush()
    retained_artifact.duplicate_of_id = removed_artifact.id

    review = EmailReviewItemModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        message_id=removed_message.id,
        artifact_id=removed_artifact.id,
        review_type="passenger_match",
        status="open",
        proposed_action="assign_document",
    )
    activity = EmailActivityEventModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=removed_connection.id,
        event_key=f"connection:{removed_connection.id}:created",
        event_type="email_connection_created",
        stage="info",
        actor_type="system",
        summary_code="email_connection_created",
    )
    db_session.add_all([review, activity])
    await db_session.flush()

    group = ClientGroupModel(
        agency_id=agency_id,
        name="Removal Test Group",
        token=f"removal-{uuid.uuid4().hex}",
        status="active",
        created_by_user_id=owner_id,
    )
    db_session.add(group)
    await db_session.flush()
    batch = DocumentDistributionBatchModel(
        agency_id=agency_id,
        group_id=group.id,
        document_type="visa",
        status="saved",
        uploaded_count=3,
        matched_count=3,
        created_by_user_id=owner_id,
    )
    db_session.add(batch)
    await db_session.flush()

    exclusive_document = DistributedDocumentModel(
        batch_id=batch.id,
        agency_id=agency_id,
        group_id=group.id,
        document_type="visa",
        original_filename="exclusive.pdf",
        storage_key="email-integrations-canonical/exclusive.pdf",
        detected_type="visa",
        match_status="matched",
        match_confidence=1.0,
    )
    shared_document = DistributedDocumentModel(
        batch_id=batch.id,
        agency_id=agency_id,
        group_id=group.id,
        document_type="visa",
        original_filename="shared.pdf",
        storage_key="email-integrations-canonical/shared.pdf",
        detected_type="visa",
        match_status="matched",
        match_confidence=1.0,
    )
    manual_document = DistributedDocumentModel(
        batch_id=batch.id,
        agency_id=agency_id,
        group_id=group.id,
        document_type="visa",
        original_filename="manual.pdf",
        storage_key="documents/manual.pdf",
        detected_type="visa",
        match_status="matched",
        match_confidence=1.0,
    )
    db_session.add_all([exclusive_document, shared_document, manual_document])
    await db_session.flush()
    db_session.add_all(
        [
            EmailArtifactDocumentModel(
                agency_id=agency_id,
                owner_user_id=owner_id,
                artifact_id=removed_artifact.id,
                distributed_document_id=exclusive_document.id,
                result_type="created",
            ),
            EmailArtifactDocumentModel(
                agency_id=agency_id,
                owner_user_id=owner_id,
                artifact_id=removed_artifact.id,
                distributed_document_id=shared_document.id,
                result_type="created",
            ),
            EmailArtifactDocumentModel(
                agency_id=agency_id,
                owner_user_id=owner_id,
                artifact_id=retained_artifact.id,
                distributed_document_id=shared_document.id,
                result_type="existing_duplicate",
            ),
            EmailArtifactDocumentModel(
                agency_id=agency_id,
                owner_user_id=owner_id,
                artifact_id=retained_artifact.id,
                distributed_document_id=manual_document.id,
                result_type="existing_duplicate",
            ),
        ]
    )
    db_session.add_all(
        [
            NotificationModel(
                agency_id=agency_id,
                user_id=owner_id,
                type="email_deadline",
                title="Removed notification",
                message="Removed notification body",
                entity_type="email_message",
                entity_id=str(removed_message.id),
                category="email_operations",
            ),
            AuditLogModel(
                agency_id=agency_id,
                user_id=owner_id,
                action="email_review_resolved",
                entity_type="email_review",
                entity_id=str(review.id),
            ),
            AuditLogModel(
                agency_id=agency_id,
                user_id=owner_id,
                action="email_connection_created",
                entity_type="email_connection",
                entity_id=str(removed_connection.id),
            ),
            AuditLogModel(
                agency_id=agency_id,
                user_id=owner_id,
                action="email_connection_created",
                entity_type="email_connection",
                entity_id=str(retained_connection.id),
            ),
        ]
    )
    await db_session.commit()

    result = await purge_email_connection_records(
        db_session,
        connection=removed_connection,
    )
    await db_session.commit()

    assert result.message_count == 1
    assert result.artifact_count == 1
    assert result.review_count == 1
    assert result.activity_count == 1
    assert result.document_count == 1
    assert result.notification_count == 1
    assert result.audit_log_count == 0
    assert set(result.storage_keys) == {
        "email-integrations/removed/staged.pdf",
        "email-integrations-canonical/exclusive.pdf",
    }

    assert await db_session.get(EmailConnectionModel, removed_connection.id) is None
    assert await db_session.get(EmailMessageModel, removed_message.id) is None
    assert await db_session.get(EmailArtifactModel, removed_artifact.id) is None
    assert await db_session.get(EmailReviewItemModel, review.id) is None
    assert await db_session.get(EmailAiAnalysisModel, analysis.id) is None
    assert await db_session.get(EmailAiFeedbackModel, feedback.id) is None
    assert await db_session.get(DistributedDocumentModel, exclusive_document.id) is None

    retained = await db_session.get(EmailArtifactModel, retained_artifact.id)
    assert retained is not None
    assert retained.duplicate_of_id is None
    assert await db_session.get(EmailConnectionModel, retained_connection.id) is not None
    assert await db_session.get(EmailMessageModel, retained_message.id) is not None
    assert await db_session.get(DistributedDocumentModel, shared_document.id) is not None
    assert await db_session.get(DistributedDocumentModel, manual_document.id) is not None
    assert await db_session.get(DocumentDistributionBatchModel, batch.id) is not None

    retained_audits = (
        await db_session.scalars(
            select(AuditLogModel).where(
                AuditLogModel.entity_type == "email_connection",
                AuditLogModel.entity_id == str(retained_connection.id),
            )
        )
    ).all()
    removed_audits = (
        await db_session.scalars(
            select(AuditLogModel).where(
                AuditLogModel.entity_id.in_([str(removed_connection.id), str(review.id)])
            )
        )
    ).all()
    assert len(retained_audits) == 1
    assert {(item.entity_type, item.entity_id) for item in removed_audits} == {
        ("email_connection", str(removed_connection.id)),
        ("email_review", str(review.id)),
    }
