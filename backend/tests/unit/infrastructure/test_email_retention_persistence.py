"""Retention commits the intended bounded content changes before storage cleanup."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailAiFeedbackModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import (
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailOAuthStateModel,
)
from app.infrastructure.database.models import AgencyModel, NotificationModel, UserModel
from app.infrastructure.email import task_retention
from app.infrastructure.email import tasks as email_tasks


@pytest.mark.parametrize("storage_failure", [None, "delete", "reconcile"])
async def test_retention_scrubs_persisted_content_and_keeps_current_or_unfinished_items(
    db_session, monkeypatch, storage_failure
):
    now = datetime.now(UTC)
    old = now - timedelta(days=31)
    agency = AgencyModel(id=uuid.uuid4(), name="Synthetic", email="agency@example.test")
    db_session.add(agency)
    await db_session.flush()
    owner = UserModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        email="owner@example.test",
        full_name="Owner",
        role="agency_staff",
        hashed_password="unused",
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
    await db_session.flush()
    message = EmailMessageModel(
        agency_id=agency.id,
        owner_user_id=owner.id,
        connection_id=connection.id,
        provider_message_id="old-message",
        received_at=old,
        subject="Retained subject",
        body_excerpt="Old body",
    )
    current = EmailMessageModel(
        agency_id=agency.id,
        owner_user_id=owner.id,
        connection_id=connection.id,
        provider_message_id="current-message",
        received_at=now,
        body_excerpt="Current body",
    )
    db_session.add_all([message, current])
    await db_session.flush()
    artifacts = [
        EmailArtifactModel(
            agency_id=agency.id,
            owner_user_id=owner.id,
            message_id=message.id,
            provider_artifact_id=name,
            kind="attachment",
            storage_key=f"email-integrations/{name}.pdf",
            processing_status=status,
            updated_at=updated,
        )
        for name, status, updated in (
            ("expired", "completed", old),
            ("unfinished", "pending", old),
            ("recent", "completed", now),
        )
    ]
    analysis = EmailAiAnalysisModel(
        agency_id=agency.id,
        owner_user_id=owner.id,
        connection_id=connection.id,
        message_id=message.id,
        status="completed",
        input_hash="a" * 64,
        prompt_schema_version="test-v1",
        config_version="test-v1",
        ai_model="synthetic",
        summary="Old summary",
        result_json={"value": "old"},
        context_manifest={"value": "old"},
        updated_at=old,
    )
    db_session.add_all([*artifacts, analysis])
    await db_session.flush()
    scope = dict(
        agency_id=agency.id,
        owner_user_id=owner.id,
        connection_id=connection.id,
        message_id=message.id,
        analysis_id=analysis.id,
    )
    deadline = EmailDetectedDeadlineModel(
        **scope,
        deadline_type="payment",
        source_phrase="Old phrase",
        source_fingerprint="b" * 64,
        source_timezone="UTC",
        confidence=0.9,
        resolution_evidence={"value": "old"},
        updated_at=old,
    )
    proposal = EmailActionProposalModel(
        **scope,
        action_type="create_task",
        risk_level="low",
        status="proposed",
        explanation="Old explanation",
        payload_json={"value": "old"},
        confidence=0.9,
        idempotency_key="c" * 64,
        decision_note="Old note",
        execution_result={"value": "old"},
        updated_at=old,
    )
    draft = EmailReplyDraftModel(
        **scope,
        subject="Old draft",
        body_text="Old body",
        recipients_json=["supplier@example.test"],
        updated_at=old,
    )
    feedback = EmailAiFeedbackModel(
        **scope,
        feedback_type="correction",
        field_name="summary",
        original_value={"value": "old"},
        corrected_value={"value": "new"},
        note="Old note",
        created_by_user_id=owner.id,
        created_at=old,
    )
    notification = NotificationModel(
        agency_id=agency.id,
        user_id=owner.id,
        type="email_ai_deadline",
        title="Retained title",
        message="Old notification",
        category="email_operations",
        metadata_json={"value": "old"},
        created_at=old,
    )
    other_notification = NotificationModel(
        agency_id=agency.id,
        user_id=owner.id,
        type="security",
        title="Security",
        message="Keep unrelated notification",
        created_at=old,
    )
    oauth = EmailOAuthStateModel(
        agency_id=agency.id,
        user_id=owner.id,
        provider="gmail",
        state_hash="d" * 64,
        code_verifier_ciphertext=b"unused",
        created_at=old,
        expires_at=old + timedelta(minutes=10),
    )
    db_session.add_all(
        [deadline, proposal, draft, feedback, notification, other_notification, oauth]
    )
    await db_session.commit()
    draft_id, oauth_id = draft.id, oauth.id

    @asynccontextmanager
    async def session_factory():
        yield db_session

    async def delete(keys):
        # The database has already committed the reference removal.
        assert not db_session.in_transaction()
        assert keys == ["email-integrations/expired.pdf"]
        if storage_failure == "delete":
            raise RuntimeError("synthetic object deletion failure")
        return len(keys)

    async def reconcile(**kwargs):
        assert kwargs["storage"] is storage
        if storage_failure == "reconcile":
            raise RuntimeError("synthetic object listing failure")
        return 3

    storage = SimpleNamespace(delete_files=AsyncMock(side_effect=delete))
    reconcile_mock = AsyncMock(side_effect=reconcile)
    monkeypatch.setattr(task_retention, "AsyncSessionFactory", session_factory)
    monkeypatch.setattr(
        task_retention,
        "get_settings",
        lambda: SimpleNamespace(
            email_content_retention_days=30, email_storage_orphan_grace_hours=24
        ),
    )
    monkeypatch.setattr(task_retention, "MinioStorageRepository", lambda: storage)
    monkeypatch.setattr(task_retention, "_reconcile_orphaned_email_storage", reconcile_mock)
    assert await email_tasks._apply_email_retention() == (
        8 if storage_failure == "reconcile" else 11
    )
    storage.delete_files.assert_awaited_once_with(["email-integrations/expired.pdf"])
    reconcile_mock.assert_awaited_once()
    await db_session.refresh(message)
    await db_session.refresh(current)
    await db_session.refresh(analysis)
    await db_session.refresh(deadline)
    await db_session.refresh(proposal)
    await db_session.refresh(feedback)
    await db_session.refresh(notification)
    await db_session.refresh(other_notification)
    assert message.body_excerpt == "" and message.subject == "Retained subject"
    assert current.body_excerpt == "Current body"
    assert (
        analysis.summary is None and analysis.result_json == {} and analysis.context_manifest == {}
    )
    assert (
        deadline.source_phrase == "[retained content removed]"
        and deadline.resolution_evidence == {}
    )
    assert proposal.explanation == "[retained content removed]" and proposal.payload_json == {}
    assert proposal.decision_note is None and proposal.execution_result == {}
    assert (
        feedback.original_value == {} and feedback.corrected_value == {} and feedback.note is None
    )
    assert notification.message == "[retained content removed]" and notification.metadata_json == {}
    assert other_notification.message == "Keep unrelated notification"
    assert await db_session.get(EmailReplyDraftModel, draft_id) is None
    assert await db_session.get(EmailOAuthStateModel, oauth_id) is None
    remaining = dict(
        (
            await db_session.execute(
                select(EmailArtifactModel.provider_artifact_id, EmailArtifactModel.storage_key)
            )
        ).all()
    )
    assert remaining == {
        "expired": None,
        "unfinished": "email-integrations/unfinished.pdf",
        "recent": "email-integrations/recent.pdf",
    }
