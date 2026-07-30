from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config.settings import Settings
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailAiFeedbackModel,
    EmailAiRolloutPolicyModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    NotificationModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.email import ai_runtime
from app.presentation.api.v1.routes import email_ai_inbox as email_ai_inbox_routes
from app.presentation.api.v1.routes import email_integrations as email_integration_routes
from app.presentation.api.v1.routes.email_ai_inbox import (
    _refresh_analysis_attention,
    create_email_ai_feedback,
    decide_email_deadline,
    decide_email_proposal,
    decide_email_reply_draft,
    email_message_intelligence,
    email_operations_inbox,
    retry_email_ai_analysis,
    update_email_reply_draft,
)
from app.presentation.api.v1.routes.email_integrations import (
    email_message_detail,
    email_review_options,
    list_email_connections,
    resolve_email_review,
    update_connection_ai_settings,
)
from app.presentation.api.v1.schemas.email_ai_schemas import (
    DecideEmailDeadlineRequest,
    DecideEmailDraftRequest,
    DecideEmailProposalRequest,
    EmailAiCorrectionValue,
    EmailAiFeedbackRequest,
    UpdateEmailReplyDraftRequest,
)
from app.presentation.api.v1.schemas.email_integration_schemas import (
    EmailAiConnectionSettingsRequest,
    ResolveEmailReviewRequest,
)


def _user(
    user_id: uuid.UUID,
    *,
    agency_id: uuid.UUID | None,
    role: UserRole,
) -> User:
    return User(
        id=user_id,
        email=f"{user_id}@example.invalid",
        hashed_password="not-used",
        full_name="Synthetic User",
        role=role,
        agency_id=agency_id,
    )


def _feedback_request(
    analysis: EmailAiAnalysisModel,
    *,
    feedback_type: str,
    field_name: str = "analysis",
    correction: EmailAiCorrectionValue | None = None,
    note: str | None = None,
) -> EmailAiFeedbackRequest:
    updated_at = analysis.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return EmailAiFeedbackRequest(
        feedback_type=feedback_type,
        field_name=field_name,
        expected_status=analysis.status,
        expected_updated_at=updated_at,
        correction=correction,
        note=note,
    )


@pytest.mark.asyncio
async def test_connection_opt_in_reports_rollout_policy_as_inactive(
    db_session,
    monkeypatch,
) -> None:
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    db_session.add(
        AgencyModel(
            id=agency_id,
            name="Policy Agency",
            email="policy-agency@example.test",
            is_active=True,
        )
    )
    db_session.add(
        UserModel(
            id=owner_id,
            email="policy-owner@example.test",
            hashed_password="not-used",
            full_name="Policy Owner",
            role="agency_staff",
            agency_id=agency_id,
            is_active=True,
        )
    )
    connection = EmailConnectionModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        provider="gmail",
        provider_account_id="policy-provider",
        email_address="policy-owner@example.test",
        status="active",
        ai_processing_enabled=False,
        created_by_user_id=owner_id,
    )
    db_session.add(connection)
    await db_session.flush()
    db_session.add(
        EmailAiRolloutPolicyModel(
            agency_id=agency_id,
            owner_user_id=owner_id,
            scope_type="user",
            enabled=False,
            updated_by_user_id=owner_id,
        )
    )
    await db_session.flush()
    monkeypatch.setattr(
        email_integration_routes,
        "get_settings",
        lambda: Settings(
            app_secret_key="test-secret",
            email_integrations_enabled=True,
            email_sync_enabled=True,
            email_ai_enabled=True,
            google_api_key="test-provider-key",
            _env_file=None,
        ),
    )

    response = await update_connection_ai_settings(
        connection_id=connection.id,
        payload=EmailAiConnectionSettingsRequest(enabled=True),
        current_user=_user(
            owner_id,
            agency_id=agency_id,
            role=UserRole.AGENCY_STAFF,
        ),
        session=db_session,
    )

    assert response.enabled is True
    assert response.effective_enabled is False
    assert "safety control" in response.message
    assert connection.ai_processing_enabled is True
    assert connection.ai_enabled_at is not None

    listed = await list_email_connections(
        current_user=_user(
            owner_id,
            agency_id=agency_id,
            role=UserRole.AGENCY_STAFF,
        ),
        session=db_session,
    )
    assert len(listed) == 1
    assert listed[0].ai_processing_enabled is True
    assert listed[0].ai_effective_enabled is False


@pytest.mark.asyncio
async def test_disabling_then_reenabling_mailbox_starts_a_new_consent_epoch(
    db_session,
    monkeypatch,
) -> None:
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    db_session.add(
        UserModel(
            id=owner_id,
            email="resume-owner@example.test",
            hashed_password="not-used",
            full_name="Resume Owner",
            role="agency_staff",
            agency_id=agency_id,
            is_active=True,
        )
    )
    connection = EmailConnectionModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        provider="gmail",
        provider_account_id="resume-provider",
        email_address="resume-owner@example.test",
        status="active",
        ai_processing_enabled=True,
        created_by_user_id=owner_id,
    )
    db_session.add(connection)
    await db_session.flush()
    message = EmailMessageModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        provider_message_id="resume-message",
        sender_address="supplier@example.test",
        subject="Please confirm",
        body_excerpt="Please confirm tomorrow.",
        received_at=datetime.now(tz=UTC),
        relevance_status="relevant",
        processing_status="completed",
    )
    db_session.add(message)
    await db_session.flush()
    analysis = EmailAiAnalysisModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        message_id=message.id,
        status="processing",
        input_hash="f" * 64,
        prompt_schema_version=ai_runtime.EMAIL_AI_SCHEMA_VERSION,
        config_version="v1",
        ai_model="configured-test-model",
        attempt_count=3,
        lease_token="a" * 32,
        lease_expires_at=datetime.now(tz=UTC) + timedelta(minutes=2),
    )
    db_session.add(analysis)
    await db_session.flush()
    owner = _user(
        owner_id,
        agency_id=agency_id,
        role=UserRole.AGENCY_STAFF,
    )

    await update_connection_ai_settings(
        connection_id=connection.id,
        payload=EmailAiConnectionSettingsRequest(enabled=False),
        current_user=owner,
        session=db_session,
    )
    await db_session.refresh(analysis)
    assert analysis.status == "ignored"
    assert analysis.attempt_count == 3
    assert analysis.lease_token is None
    assert analysis.last_error_code == "account_ai_opted_out"

    await update_connection_ai_settings(
        connection_id=connection.id,
        payload=EmailAiConnectionSettingsRequest(enabled=True),
        current_user=owner,
        session=db_session,
    )
    assert connection.ai_enabled_at is not None
    new_message = EmailMessageModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        provider_message_id="new-consent-message",
        sender_address="supplier@example.test",
        subject="New post-consent request",
        body_excerpt="Please confirm the new request.",
        received_at=connection.ai_enabled_at + timedelta(seconds=1),
        relevance_status="relevant",
        processing_status="completed",
    )
    db_session.add(new_message)
    await db_session.flush()

    class SharedSessionContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(
        ai_runtime,
        "AsyncSessionFactory",
        lambda: SharedSessionContext(),
    )
    claims = await ai_runtime.seed_and_claim_email_ai_work(
        Settings(
            app_secret_key="test-secret",
            email_integrations_enabled=True,
            email_sync_enabled=True,
            email_ai_enabled=True,
            email_ai_max_attempts=3,
            google_api_key="test-provider-key",
            _env_file=None,
        )
    )

    assert [claim.message_id for claim in claims] == [new_message.id]
    assert analysis.status == "ignored"
    assert analysis.attempt_count == 3


@pytest.mark.asyncio
async def test_review_options_message_context_is_owner_and_agency_scoped(
    db_session,
) -> None:
    first_agency_id = uuid.uuid4()
    second_agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    other_owner_id = uuid.uuid4()
    db_session.add_all(
        [
            AgencyModel(
                id=first_agency_id,
                name="First Review Agency",
                email="first-review-agency@example.test",
                is_active=True,
            ),
            AgencyModel(
                id=second_agency_id,
                name="Second Review Agency",
                email="second-review-agency@example.test",
                is_active=True,
            ),
            UserModel(
                id=owner_id,
                email="review-super-admin@example.test",
                hashed_password="not-used",
                full_name="Review Super Admin",
                role="super_admin",
                is_active=True,
            ),
            UserModel(
                id=other_owner_id,
                email="review-other-owner@example.test",
                hashed_password="not-used",
                full_name="Review Other Owner",
                role="agency_staff",
                agency_id=first_agency_id,
                is_active=True,
            ),
        ]
    )
    await db_session.flush()
    first_connection = EmailConnectionModel(
        agency_id=first_agency_id,
        owner_user_id=owner_id,
        provider="gmail",
        provider_account_id="review-first-provider",
        email_address="review-first@example.test",
        created_by_user_id=owner_id,
    )
    second_connection = EmailConnectionModel(
        agency_id=second_agency_id,
        owner_user_id=owner_id,
        provider="outlook",
        provider_account_id="review-second-provider",
        email_address="review-second@example.test",
        created_by_user_id=owner_id,
    )
    other_connection = EmailConnectionModel(
        agency_id=first_agency_id,
        owner_user_id=other_owner_id,
        provider="gmail",
        provider_account_id="review-other-provider",
        email_address="review-other@example.test",
        created_by_user_id=other_owner_id,
    )
    db_session.add_all(
        [first_connection, second_connection, other_connection]
    )
    await db_session.flush()
    first_message = EmailMessageModel(
        agency_id=first_agency_id,
        owner_user_id=owner_id,
        connection_id=first_connection.id,
        provider_message_id="review-first-message",
        sender_address="supplier@example.test",
        subject="First agency review",
        received_at=datetime.now(tz=UTC),
    )
    other_message = EmailMessageModel(
        agency_id=first_agency_id,
        owner_user_id=other_owner_id,
        connection_id=other_connection.id,
        provider_message_id="review-other-message",
        sender_address="supplier@example.test",
        subject="Other owner's review",
        received_at=datetime.now(tz=UTC),
    )
    db_session.add_all([first_message, other_message])
    await db_session.flush()
    first_group = ClientGroupModel(
        agency_id=first_agency_id,
        name="First Context Group",
        token=f"first-context-{uuid.uuid4().hex}",
        status="active",
        created_by_user_id=owner_id,
    )
    second_group = ClientGroupModel(
        agency_id=second_agency_id,
        name="Second Context Group",
        token=f"second-context-{uuid.uuid4().hex}",
        status="active",
        created_by_user_id=owner_id,
    )
    db_session.add_all([first_group, second_group])
    await db_session.flush()
    first_passenger = PassportSubmissionModel(
        group_id=first_group.id,
        agency_id=first_agency_id,
        client_name="First Context Passenger",
        image_s3_key="tests/first-context.jpg",
    )
    second_passenger = PassportSubmissionModel(
        group_id=second_group.id,
        agency_id=second_agency_id,
        client_name="Second Context Passenger",
        image_s3_key="tests/second-context.jpg",
    )
    db_session.add_all([first_passenger, second_passenger])
    await db_session.flush()
    current_user = _user(
        owner_id,
        agency_id=None,
        role=UserRole.SUPER_ADMIN,
    )

    no_context = await email_review_options(
        group_id=None,
        message_id=None,
        current_user=current_user,
        session=db_session,
    )
    assert {group.id for group in no_context.groups} == {
        first_group.id,
        second_group.id,
    }

    first_context = await email_review_options(
        group_id=first_group.id,
        message_id=first_message.id,
        current_user=current_user,
        session=db_session,
    )
    assert [group.id for group in first_context.groups] == [
        first_group.id
    ]
    assert [passenger.id for passenger in first_context.passengers] == [
        first_passenger.id
    ]

    with pytest.raises(HTTPException) as cross_agency_group:
        await email_review_options(
            group_id=second_group.id,
            message_id=first_message.id,
            current_user=current_user,
            session=db_session,
        )
    assert cross_agency_group.value.status_code == 404

    with pytest.raises(HTTPException) as cross_owner_message:
        await email_review_options(
            group_id=None,
            message_id=other_message.id,
            current_user=current_user,
            session=db_session,
        )
    assert cross_owner_message.value.status_code == 404


@pytest.mark.asyncio
async def test_failed_analysis_retry_is_owner_scoped_bounded_and_audited(
    db_session,
    monkeypatch,
) -> None:
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    other_id = uuid.uuid4()
    db_session.add(
        AgencyModel(
            id=agency_id,
            name="Retry Agency",
            email="retry-agency@example.test",
            is_active=True,
        )
    )
    for user_id, email in (
        (owner_id, "retry-owner@example.test"),
        (other_id, "retry-other@example.test"),
    ):
        db_session.add(
            UserModel(
                id=user_id,
                email=email,
                hashed_password="not-used",
                full_name="Retry User",
                role="agency_staff",
                agency_id=agency_id,
                is_active=True,
            )
        )
    connection = EmailConnectionModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        provider="gmail",
        provider_account_id="retry-provider",
        email_address="retry-owner@example.test",
        status="active",
        ai_processing_enabled=True,
        ai_enabled_at=datetime.now(tz=UTC) - timedelta(minutes=5),
        created_by_user_id=owner_id,
    )
    db_session.add(connection)
    await db_session.flush()
    message = EmailMessageModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        provider_message_id="retry-message",
        sender_address="supplier@example.test",
        subject="Retry this analysis",
        body_excerpt="Please review tomorrow.",
        received_at=datetime.now(tz=UTC),
        relevance_status="relevant",
        processing_status="completed",
    )
    db_session.add(message)
    await db_session.flush()
    analysis = EmailAiAnalysisModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        message_id=message.id,
        status="failed",
        input_hash="9" * 64,
        prompt_schema_version="old-schema",
        config_version="old-config",
        ai_model="old-model",
        attempt_count=3,
        last_error_code="provider_unavailable",
        summary="Stale failure output",
        confidence=0.1,
        needs_attention=True,
        completed_at=datetime.now(tz=UTC),
        result_json={"manual_retry_generation": 0},
    )
    db_session.add(analysis)
    await db_session.flush()
    old_notification = NotificationModel(
        agency_id=agency_id,
        user_id=owner_id,
        type="email_ai_failure",
        title="Old failure",
        message="The old retry cycle failed.",
        entity_type="email_message",
        entity_id=str(message.id),
        category="email_operations",
        dedupe_key=f"email-ai:{analysis.id}:attention:0",
        is_read=False,
    )
    other_notification = NotificationModel(
        agency_id=agency_id,
        user_id=other_id,
        type="email_ai_failure",
        title="Other owner",
        message="Must not be changed.",
        entity_type="email_message",
        entity_id=str(message.id),
        category="email_operations",
        dedupe_key=f"email-ai:{analysis.id}:other-owner",
        is_read=False,
    )
    db_session.add_all([old_notification, other_notification])
    await db_session.flush()
    owner = _user(
        owner_id,
        agency_id=agency_id,
        role=UserRole.AGENCY_STAFF,
    )
    other = _user(
        other_id,
        agency_id=agency_id,
        role=UserRole.AGENCY_STAFF,
    )
    monkeypatch.setattr(
        email_ai_inbox_routes,
        "get_settings",
        lambda: Settings(
            app_secret_key="test-secret",
            email_integrations_enabled=True,
            email_sync_enabled=True,
            email_ai_enabled=True,
            email_ai_max_attempts=3,
            email_ai_max_manual_retries=2,
            google_api_key="test-provider-key",
            gemini_model="configured-test-model",
            gemini_config_version="retry-v2",
            _env_file=None,
        ),
    )

    with pytest.raises(HTTPException) as other_retry:
        await retry_email_ai_analysis(
            analysis_id=analysis.id,
            current_user=other,
            session=db_session,
        )
    assert other_retry.value.status_code == 404

    policy = EmailAiRolloutPolicyModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        scope_type="user",
        enabled=False,
        updated_by_user_id=owner_id,
    )
    db_session.add(policy)
    await db_session.flush()
    with pytest.raises(HTTPException) as blocked_retry:
        await retry_email_ai_analysis(
            analysis_id=analysis.id,
            current_user=owner,
            session=db_session,
        )
    assert blocked_retry.value.status_code == 409
    await db_session.delete(policy)
    await db_session.flush()

    connection.ai_enabled_at = message.received_at + timedelta(seconds=1)
    await db_session.flush()
    with pytest.raises(HTTPException) as old_consent_retry:
        await retry_email_ai_analysis(
            analysis_id=analysis.id,
            current_user=owner,
            session=db_session,
        )
    assert old_consent_retry.value.status_code == 409
    assert analysis.status == "failed"
    assert old_notification.is_read is False
    connection.ai_enabled_at = message.received_at - timedelta(minutes=1)
    await db_session.flush()

    retried = await retry_email_ai_analysis(
        analysis_id=analysis.id,
        current_user=owner,
        session=db_session,
    )
    assert retried.status == "pending"
    assert retried.retry_generation == 1
    assert analysis.status == "pending"
    assert analysis.attempt_count == 0
    assert analysis.summary is None
    assert analysis.confidence is None
    assert analysis.needs_attention is False
    assert analysis.prompt_schema_version == ai_runtime.EMAIL_AI_SCHEMA_VERSION
    assert analysis.config_version == "retry-v2"
    assert analysis.ai_model == "configured-test-model"
    assert analysis.result_json["manual_retry_generation"] == 1
    await db_session.refresh(old_notification)
    await db_session.refresh(other_notification)
    assert old_notification.is_read is True
    assert other_notification.is_read is False

    retry_event = (
        await db_session.execute(
            select(EmailActivityEventModel).where(
                EmailActivityEventModel.event_type
                == "ai_analysis_retry_requested",
                EmailActivityEventModel.owner_user_id == owner_id,
            )
        )
    ).scalar_one()
    assert retry_event.actor_user_id == owner_id
    assert retry_event.details["retry_generation"] == 1

    with pytest.raises(HTTPException) as duplicate_retry:
        await retry_email_ai_analysis(
            analysis_id=analysis.id,
            current_user=owner,
            session=db_session,
        )
    assert duplicate_retry.value.status_code == 409

    analysis.status = "failed"
    analysis.attempt_count = 3
    analysis.last_error_code = "timeout"
    analysis.result_json = {"manual_retry_generation": 1}
    second_retry = await retry_email_ai_analysis(
        analysis_id=analysis.id,
        current_user=owner,
        session=db_session,
    )
    assert second_retry.retry_generation == 2
    analysis.status = "failed"
    analysis.result_json = {"manual_retry_generation": 2}
    with pytest.raises(HTTPException) as retry_limit:
        await retry_email_ai_analysis(
            analysis_id=analysis.id,
            current_user=owner,
            session=db_session,
        )
    assert retry_limit.value.status_code == 409


@pytest.mark.asyncio
async def test_ai_inbox_is_private_even_within_agency_and_for_super_admin(
    db_session,
) -> None:
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    connection = EmailConnectionModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        provider="gmail",
        provider_account_id="provider-owner",
        email_address="owner@example.invalid",
        created_by_user_id=owner_id,
    )
    db_session.add(connection)
    await db_session.flush()
    hidden_group = ClientGroupModel(
        agency_id=agency_id,
        name="Private Group",
        token=f"private-{uuid.uuid4().hex}",
        status="active",
        created_by_user_id=uuid.uuid4(),
    )
    db_session.add(hidden_group)
    await db_session.flush()
    visible_group = ClientGroupModel(
        agency_id=agency_id,
        name="Owner Visible Group",
        token=f"visible-{uuid.uuid4().hex}",
        status="active",
        created_by_user_id=owner_id,
    )
    db_session.add(visible_group)
    await db_session.flush()
    message = EmailMessageModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        provider_message_id="message-owner",
        sender_address="supplier@example.invalid",
        subject="Arrival details",
        body_excerpt="Please confirm tomorrow.",
        received_at=datetime.now(tz=UTC),
        group_id=hidden_group.id,
    )
    db_session.add(message)
    await db_session.flush()
    analysis = EmailAiAnalysisModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        message_id=message.id,
        status="completed",
        input_hash="a" * 64,
        prompt_schema_version="v1",
        config_version="v1",
        ai_model="configured-test-model",
        intent="information_request",
        priority="normal",
        summary="Arrival details need confirmation.",
        confidence=0.91,
        result_json={
            "evidence": ["explicit request"],
            "linked_group_id": str(visible_group.id),
            "candidate_links": [
                {
                    "alias": "group_001",
                    "confidence": 0.96,
                    "rationale": "The visible group name appears in the email.",
                },
                {
                    "alias": "group_002",
                    "confidence": 0.95,
                    "rationale": "A currently hidden group also matched.",
                },
            ],
        },
        context_manifest={
            "aliases": {
                "group_001": {
                    "entity_type": "group",
                    "entity_id": str(visible_group.id),
                },
                "group_002": {
                    "entity_type": "group",
                    "entity_id": str(hidden_group.id),
                },
            }
        },
    )
    db_session.add(analysis)
    await db_session.flush()
    db_session.add(
        EmailDetectedDeadlineModel(
            agency_id=agency_id,
            owner_user_id=owner_id,
            connection_id=connection.id,
            message_id=message.id,
            analysis_id=analysis.id,
            deadline_type="response_due",
            source_phrase="Please confirm yesterday.",
            source_fingerprint="d" * 64,
            source_timezone="UTC",
            due_at=datetime.now(tz=UTC) - timedelta(days=1),
            confidence=0.95,
            status="detected",
        )
    )
    await db_session.flush()

    owner = _user(
        owner_id,
        agency_id=agency_id,
        role=UserRole.AGENCY_STAFF,
    )
    same_agency_admin = _user(
        uuid.uuid4(),
        agency_id=agency_id,
        role=UserRole.AGENCY_ADMIN,
    )
    super_admin = _user(
        uuid.uuid4(),
        agency_id=None,
        role=UserRole.SUPER_ADMIN,
    )

    owner_detail = await email_message_intelligence(
        message_id=message.id,
        current_user=owner,
        session=db_session,
    )
    assert owner_detail.id == analysis.id
    assert owner_detail.linked_group_id == visible_group.id
    assert owner_detail.linked_group_name == visible_group.name
    assert len(owner_detail.candidate_links) == 1
    assert owner_detail.candidate_links[0].entity_id == visible_group.id
    assert owner_detail.candidate_links[0].canonical is True
    owner_inbox = await email_operations_inbox(
        view="all_activity",
        cursor=None,
        limit=30,
        current_user=owner,
        session=db_session,
    )
    assert [item.message_id for item in owner_inbox.items] == [message.id]
    assert owner_inbox.items[0].group_id == visible_group.id
    assert owner_inbox.items[0].group_name == visible_group.name
    assert owner_inbox.items[0].section == "upcoming_deadlines"
    assert owner_inbox.items[0].next_deadline is not None
    deadline_inbox = await email_operations_inbox(
        view="upcoming_deadlines",
        cursor=None,
        limit=30,
        current_user=owner,
        session=db_session,
    )
    assert [item.message_id for item in deadline_inbox.items] == [message.id]
    assert deadline_inbox.counts.completed_automatically == 0

    blocked_proposal = EmailActionProposalModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        message_id=message.id,
        analysis_id=analysis.id,
        action_type="send_email",
        risk_level="high",
        status="blocked",
        explanation="External sending is unavailable in this release.",
        confidence=0.99,
        requires_approval=False,
        idempotency_key="e" * 64,
    )
    analysis.status = "review_required"
    analysis.needs_attention = True
    db_session.add(blocked_proposal)
    await db_session.flush()
    decision = await decide_email_proposal(
        proposal_id=blocked_proposal.id,
        payload=DecideEmailProposalRequest(
            action="dismiss",
            expected_revision=1,
        ),
        current_user=owner,
        session=db_session,
    )
    assert decision.status == "dismissed"
    assert blocked_proposal.revision == 2
    assert analysis.status == "completed"
    assert analysis.needs_attention is False
    activity = (
        await db_session.execute(
            select(EmailActivityEventModel).where(
                EmailActivityEventModel.changed_entity_id == blocked_proposal.id
            )
        )
    ).scalar_one()
    assert activity.actor_user_id == owner_id
    assert activity.summary_code == "email_ai_proposal_dismissed"

    for other_user in (same_agency_admin, super_admin):
        with pytest.raises(HTTPException) as exc_info:
            await email_message_intelligence(
                message_id=message.id,
                current_user=other_user,
                session=db_session,
            )
        assert exc_info.value.status_code == 404
        private_inbox = await email_operations_inbox(
            view="all_activity",
            cursor=None,
            limit=30,
            current_user=other_user,
            session=db_session,
        )
        assert private_inbox.items == []
        assert private_inbox.counts.all_activity == 0


@pytest.mark.asyncio
async def test_deadline_draft_and_feedback_lifecycle_is_owner_scoped_and_revision_safe(
    db_session,
) -> None:
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    other_id = uuid.uuid4()
    for user_id, email in (
        (owner_id, "lifecycle-owner@example.test"),
        (other_id, "lifecycle-other@example.test"),
    ):
        db_session.add(
            UserModel(
                id=user_id,
                email=email,
                hashed_password="not-used",
                full_name="Lifecycle User",
                role="agency_staff",
                agency_id=agency_id,
                is_active=True,
            )
        )
    connection = EmailConnectionModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        provider="outlook",
        provider_account_id="lifecycle-provider",
        email_address="lifecycle-owner@example.test",
        created_by_user_id=owner_id,
    )
    db_session.add(connection)
    await db_session.flush()
    message = EmailMessageModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        provider_message_id="lifecycle-message",
        sender_address="supplier@example.test",
        subject="Reply required",
        body_excerpt="Please reply tomorrow.",
        received_at=datetime.now(tz=UTC),
    )
    db_session.add(message)
    await db_session.flush()
    analysis = EmailAiAnalysisModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        message_id=message.id,
        status="review_required",
        input_hash="1" * 64,
        prompt_schema_version="v1",
        config_version="v1",
        ai_model="configured-test-model",
        intent="information_request",
        priority="normal",
        summary="A response is requested.",
        confidence=0.96,
        needs_attention=True,
        result_json={"relevance": "relevant"},
    )
    db_session.add(analysis)
    await db_session.flush()
    deadline = EmailDetectedDeadlineModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        message_id=message.id,
        analysis_id=analysis.id,
        deadline_type="response_due",
        source_phrase="Please reply tomorrow.",
        source_fingerprint="2" * 64,
        source_timezone="UTC",
        due_at=datetime.now(tz=UTC) + timedelta(days=1),
        confidence=0.96,
        status="review_required",
    )
    draft = EmailReplyDraftModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        message_id=message.id,
        analysis_id=analysis.id,
        recipients_json=["supplier@example.test"],
        subject="Re: Reply required",
        body_text="Thank you. We will confirm shortly.",
        status="prepared",
    )
    db_session.add_all([deadline, draft])
    await db_session.flush()
    owner = _user(
        owner_id,
        agency_id=agency_id,
        role=UserRole.AGENCY_STAFF,
    )
    other = _user(
        other_id,
        agency_id=agency_id,
        role=UserRole.AGENCY_STAFF,
    )
    deadline.updated_at = datetime.now(tz=UTC) - timedelta(minutes=1)
    await db_session.flush()
    original_deadline_updated_at = deadline.updated_at
    if original_deadline_updated_at.tzinfo is None:
        original_deadline_updated_at = (
            original_deadline_updated_at.replace(tzinfo=UTC)
        )

    analysis.status = "processing"
    with pytest.raises(HTTPException) as unfinished_feedback:
        await create_email_ai_feedback(
            analysis_id=analysis.id,
            payload=EmailAiFeedbackRequest.model_construct(
                feedback_type="confirmation",
                field_name="analysis",
                expected_status="processing",
                expected_updated_at=analysis.updated_at,
                correction=None,
                note=None,
            ),
            current_user=owner,
            session=db_session,
        )
    assert unfinished_feedback.value.status_code == 409
    analysis.status = "review_required"

    with pytest.raises(HTTPException) as other_deadline:
        await decide_email_deadline(
            deadline_id=deadline.id,
            payload=DecideEmailDeadlineRequest(
                action="acknowledge",
                expected_status="review_required",
                expected_updated_at=original_deadline_updated_at,
            ),
            current_user=other,
            session=db_session,
        )
    assert other_deadline.value.status_code == 404

    acknowledged = await decide_email_deadline(
        deadline_id=deadline.id,
        payload=DecideEmailDeadlineRequest(
            action="acknowledge",
            expected_status="review_required",
            expected_updated_at=original_deadline_updated_at,
        ),
        current_user=owner,
        session=db_session,
    )
    assert acknowledged.status == "acknowledged"
    assert acknowledged.updated_at.tzinfo is not None
    with pytest.raises(HTTPException) as stale_deadline:
        await decide_email_deadline(
            deadline_id=deadline.id,
            payload=DecideEmailDeadlineRequest(
                action="complete",
                expected_status="review_required",
                expected_updated_at=original_deadline_updated_at,
            ),
            current_user=owner,
            session=db_session,
    )
    assert stale_deadline.value.status_code == 409
    with pytest.raises(HTTPException) as stale_deadline_timestamp:
        await decide_email_deadline(
            deadline_id=deadline.id,
            payload=DecideEmailDeadlineRequest(
                action="complete",
                expected_status="acknowledged",
                expected_updated_at=original_deadline_updated_at,
            ),
            current_user=owner,
            session=db_session,
        )
    assert stale_deadline_timestamp.value.status_code == 409
    with pytest.raises(ValueError, match="UTC offset"):
        DecideEmailDeadlineRequest(
            action="complete",
            expected_status="acknowledged",
            expected_updated_at=datetime(2026, 8, 1, 9, 30),
        )

    edited = await update_email_reply_draft(
        draft_id=draft.id,
        payload=UpdateEmailReplyDraftRequest(
            subject="Re: Updated reply",
            body_text="Updated grounded draft.",
            expected_revision=1,
        ),
        current_user=owner,
        session=db_session,
    )
    assert edited.revision == 2
    assert edited.status == "edited"
    draft_feedback = (
        await db_session.execute(
            select(EmailAiFeedbackModel).where(
                EmailAiFeedbackModel.analysis_id == analysis.id,
                EmailAiFeedbackModel.field_name == "draft",
            )
        )
    ).scalar_one()
    assert draft_feedback.original_value["subject"] == "Re: Reply required"
    assert draft_feedback.corrected_value["subject"] == "Re: Updated reply"
    with pytest.raises(HTTPException) as stale_edit:
        await update_email_reply_draft(
            draft_id=draft.id,
            payload=UpdateEmailReplyDraftRequest(
                subject="Stale",
                body_text="Stale content.",
                expected_revision=1,
            ),
            current_user=owner,
            session=db_session,
        )
    assert stale_edit.value.status_code == 409

    with pytest.raises(HTTPException) as other_draft:
        await decide_email_reply_draft(
            draft_id=draft.id,
            payload=DecideEmailDraftRequest(
                action="approve",
                expected_revision=2,
            ),
            current_user=other,
            session=db_session,
        )
    assert other_draft.value.status_code == 404
    approved = await decide_email_reply_draft(
        draft_id=draft.id,
        payload=DecideEmailDraftRequest(
            action="approve",
            expected_revision=2,
        ),
        current_user=owner,
        session=db_session,
    )
    assert approved.status == "approved"
    assert approved.revision == 3
    assert approved.sending_available is False
    dismissed_draft = await decide_email_reply_draft(
        draft_id=draft.id,
        payload=DecideEmailDraftRequest(
            action="dismiss",
            expected_revision=3,
        ),
        current_user=owner,
        session=db_session,
    )
    assert dismissed_draft.status == "dismissed"

    analysis.status = "review_required"
    analysis.needs_attention = True
    analysis.result_json = {
        "relevance": "possibly_relevant",
        "candidate_ambiguity": True,
        "human_review_confirmed": False,
        "risks": [
            {
                "code": "prompt_injection",
                "level": "critical",
                "rationale": "Untrusted content attempted to override policy.",
            }
        ],
    }
    await _refresh_analysis_attention(db_session, analysis)
    assert analysis.status == "review_required"
    assert analysis.needs_attention is True
    await create_email_ai_feedback(
        analysis_id=analysis.id,
        payload=_feedback_request(
            analysis,
            feedback_type="confirmation",
        ),
        current_user=owner,
        session=db_session,
    )
    assert analysis.status == "completed"
    assert analysis.needs_attention is False
    assert analysis.result_json["human_review_confirmed"] is True
    with pytest.raises(HTTPException) as duplicate_confirmation:
        await create_email_ai_feedback(
            analysis_id=analysis.id,
            payload=_feedback_request(
                analysis,
                feedback_type="confirmation",
            ),
            current_user=owner,
            session=db_session,
        )
    assert duplicate_confirmation.value.status_code == 409

    deadline.status = "detected"
    draft.status = "prepared"
    proposal = EmailActionProposalModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        message_id=message.id,
        analysis_id=analysis.id,
        action_type="send_email",
        risk_level="high",
        status="blocked",
        explanation="External sending remains blocked.",
        confidence=0.99,
        requires_approval=False,
        idempotency_key="3" * 64,
    )
    analysis.status = "review_required"
    analysis.needs_attention = True
    db_session.add(proposal)
    await db_session.flush()
    with pytest.raises(HTTPException) as other_feedback:
        await create_email_ai_feedback(
            analysis_id=analysis.id,
            payload=_feedback_request(
                analysis,
                feedback_type="dismissal",
            ),
            current_user=other,
            session=db_session,
        )
    assert other_feedback.value.status_code == 404

    await create_email_ai_feedback(
        analysis_id=analysis.id,
        payload=_feedback_request(
            analysis,
            feedback_type="dismissal",
        ),
        current_user=owner,
        session=db_session,
    )
    await db_session.refresh(deadline)
    await db_session.refresh(draft)
    await db_session.refresh(proposal)
    assert analysis.status == "ignored"
    assert analysis.needs_attention is False
    assert deadline.status == "dismissed"
    assert draft.status == "dismissed"
    assert proposal.status == "dismissed"

    corrected_group = ClientGroupModel(
        name="Corrected Operations Group",
        token=f"corrected-{uuid.uuid4()}",
        agency_id=agency_id,
        status="active",
        created_by_user_id=owner_id,
    )
    db_session.add(corrected_group)
    await db_session.flush()
    proposal.status = "blocked"
    draft.status = "prepared"
    await db_session.flush()
    stale_updated_at = analysis.updated_at
    response = await create_email_ai_feedback(
        analysis_id=analysis.id,
        payload=_feedback_request(
            analysis,
            feedback_type="correction",
            field_name="linked_group",
            correction=EmailAiCorrectionValue(
                group_id=corrected_group.id,
            ),
            note="The selected group was missing.",
        ),
        current_user=owner,
        session=db_session,
    )
    assert analysis.status == "review_required"
    assert analysis.needs_attention is True
    assert analysis.result_json["linked_group_id"] == str(corrected_group.id)
    assert analysis.result_json["linked_passenger_ids"] == []
    assert "linked_group" in analysis.result_json["human_corrected_fields"]
    assert proposal.status == "dismissed"
    assert draft.status == "dismissed"
    assert response.analysis_status == "review_required"
    feedback_row = (
        await db_session.execute(
            select(EmailAiFeedbackModel)
            .where(
                EmailAiFeedbackModel.analysis_id == analysis.id,
                EmailAiFeedbackModel.field_name == "linked_group",
            )
            .order_by(EmailAiFeedbackModel.created_at.desc())
        )
    ).scalars().first()
    assert feedback_row is not None
    assert feedback_row.original_value.get("group_id") is None
    assert feedback_row.corrected_value["group_id"] == str(
        corrected_group.id
    )
    assert feedback_row.corrected_value["generated_work_invalidated"] is True

    with pytest.raises(HTTPException) as stale_correction:
        await create_email_ai_feedback(
            analysis_id=analysis.id,
            payload=EmailAiFeedbackRequest(
                feedback_type="correction",
                field_name="summary",
                expected_status="ignored",
                expected_updated_at=(
                    stale_updated_at
                    if stale_updated_at.tzinfo is not None
                    else stale_updated_at.replace(tzinfo=UTC)
                ),
                correction=EmailAiCorrectionValue(
                    text="A stale correction must not win.",
                ),
            ),
            current_user=owner,
            session=db_session,
        )
    assert stale_correction.value.status_code == 409

    long_corrected_summary = (
        "The supplier needs a corrected response tomorrow. "
        + "Grounded operational detail " * 30
    ).strip()
    await create_email_ai_feedback(
        analysis_id=analysis.id,
        payload=_feedback_request(
            analysis,
            feedback_type="correction",
            field_name="summary",
            correction=EmailAiCorrectionValue(
                text=long_corrected_summary,
            ),
        ),
        current_user=owner,
        session=db_session,
    )
    assert analysis.summary == long_corrected_summary
    correction_events = list(
        (
            await db_session.execute(
                select(EmailActivityEventModel).where(
                    EmailActivityEventModel.message_id == message.id,
                    EmailActivityEventModel.owner_user_id == owner_id,
                    EmailActivityEventModel.event_type
                    == "ai_analysis_corrected",
                )
            )
        )
        .scalars()
        .all()
    )
    summary_event = next(
        event
        for event in correction_events
        if event.details.get("field_name") == "summary"
    )
    assert summary_event.details["before_value"] == (
        "A response is requested."
    )
    assert len(summary_event.details["after_value"]) <= 240
    assert len(summary_event.details["after_value"]) >= 200
    assert summary_event.details["after_value"].endswith("…")
    message_detail = await email_message_detail(
        message_id=message.id,
        current_user=owner,
        session=db_session,
    )
    summary_detail = next(
        event.detail
        for event in message_detail.events
        if event.id == summary_event.id
    )
    assert summary_detail is not None
    assert "Before: A response is requested." in summary_detail
    assert "After: The supplier needs a corrected response tomorrow." in (
        summary_detail
    )
    assert len(summary_detail) <= 560
    with pytest.raises(HTTPException) as other_activity_detail:
        await email_message_detail(
            message_id=message.id,
            current_user=other,
            session=db_session,
        )
    assert other_activity_detail.value.status_code == 404

    await create_email_ai_feedback(
        analysis_id=analysis.id,
        payload=_feedback_request(
            analysis,
            feedback_type="correction",
            field_name="intent",
            correction=EmailAiCorrectionValue(intent="deadline_update"),
        ),
        current_user=owner,
        session=db_session,
    )
    assert analysis.intent == "deadline_update"

    await create_email_ai_feedback(
        analysis_id=analysis.id,
        payload=_feedback_request(
            analysis,
            feedback_type="correction",
            field_name="priority",
            correction=EmailAiCorrectionValue(priority="urgent"),
        ),
        current_user=owner,
        session=db_session,
    )
    assert analysis.priority == "urgent"

    corrected_due_at = datetime.now(tz=UTC) + timedelta(hours=8)
    await create_email_ai_feedback(
        analysis_id=analysis.id,
        payload=_feedback_request(
            analysis,
            feedback_type="correction",
            field_name="deadline",
            correction=EmailAiCorrectionValue(
                deadline_id=deadline.id,
                due_at=corrected_due_at,
            ),
        ),
        current_user=owner,
        session=db_session,
    )
    assert deadline.status == "review_required"
    assert deadline.confidence == 1.0
    assert deadline.is_ambiguous is False
    assert deadline.due_at == corrected_due_at

    with pytest.raises(ValueError, match="UTC offset"):
        EmailAiFeedbackRequest(
            feedback_type="correction",
            field_name="deadline",
            expected_status="review_required",
            expected_updated_at=datetime.now(tz=UTC),
            correction=EmailAiCorrectionValue(
                due_at=datetime(2026, 8, 1, 9, 30),
            ),
        )

    other_group = ClientGroupModel(
        name="Other Operations Group",
        token=f"other-{uuid.uuid4()}",
        agency_id=agency_id,
        status="active",
        created_by_user_id=owner_id,
    )
    passenger = PassportSubmissionModel(
        group_id=corrected_group.id,
        agency_id=agency_id,
        client_name="Anita Sharma",
        image_s3_key="tests/anita.jpg",
    )
    other_passenger = PassportSubmissionModel(
        group=other_group,
        agency_id=agency_id,
        client_name="Ravi Sharma",
        image_s3_key="tests/ravi.jpg",
    )
    db_session.add_all([other_group, passenger, other_passenger])
    await db_session.flush()
    with pytest.raises(HTTPException) as cross_group_passengers:
        await create_email_ai_feedback(
            analysis_id=analysis.id,
            payload=_feedback_request(
                analysis,
                feedback_type="correction",
                field_name="linked_passengers",
                correction=EmailAiCorrectionValue(
                    passenger_ids=[passenger.id, other_passenger.id],
                ),
            ),
            current_user=owner,
            session=db_session,
        )
    assert cross_group_passengers.value.status_code == 409

    await create_email_ai_feedback(
        analysis_id=analysis.id,
        payload=_feedback_request(
            analysis,
            feedback_type="correction",
            field_name="linked_passengers",
            correction=EmailAiCorrectionValue(
                passenger_ids=[passenger.id],
            ),
        ),
        current_user=owner,
        session=db_session,
    )
    assert analysis.result_json["linked_group_id"] == str(corrected_group.id)
    assert analysis.result_json["linked_passenger_ids"] == [str(passenger.id)]

    await create_email_ai_feedback(
        analysis_id=analysis.id,
        payload=_feedback_request(
            analysis,
            feedback_type="correction",
            field_name="notification",
            correction=EmailAiCorrectionValue(
                notification_expected=False,
            ),
        ),
        current_user=owner,
        session=db_session,
    )
    assert analysis.result_json["human_notification_expected"] is False
    feedback_fields = set(
        (
            await db_session.execute(
                select(EmailAiFeedbackModel.field_name).where(
                    EmailAiFeedbackModel.analysis_id == analysis.id,
                )
            )
        ).scalars()
    )
    assert {
        "draft",
        "linked_group",
        "summary",
        "intent",
        "priority",
        "deadline",
        "linked_passengers",
        "notification",
    }.issubset(feedback_fields)

    activity_types = set(
        (
            await db_session.execute(
                select(EmailActivityEventModel.event_type).where(
                    EmailActivityEventModel.message_id == message.id,
                    EmailActivityEventModel.owner_user_id == owner_id,
                )
            )
        ).scalars()
    )
    assert {
        "ai_deadline_decided",
        "ai_reply_draft_edited",
        "ai_reply_draft_decided",
        "ai_analysis_confirmed",
        "ai_analysis_dismissed",
        "ai_analysis_corrected",
    }.issubset(activity_types)


@pytest.mark.asyncio
async def test_marking_message_unrelated_revokes_an_inflight_ai_claim(
    db_session,
) -> None:
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    db_session.add(
        AgencyModel(
            id=agency_id,
            name="Human Review Agency",
            email="human-review-agency@example.test",
            is_active=True,
        )
    )
    db_session.add(
        UserModel(
            id=owner_id,
            email="human-review-owner@example.test",
            hashed_password="not-used",
            full_name="Human Review Owner",
            role="agency_staff",
            agency_id=agency_id,
            is_active=True,
        )
    )
    enabled_at = datetime.now(tz=UTC) - timedelta(minutes=10)
    connection = EmailConnectionModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        provider="gmail",
        provider_account_id="human-review-provider",
        email_address="human-review-owner@example.test",
        status="active",
        ai_processing_enabled=True,
        ai_enabled_at=enabled_at,
        created_by_user_id=owner_id,
    )
    db_session.add(connection)
    await db_session.flush()
    message = EmailMessageModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        provider_message_id="human-review-message",
        sender_address="newsletter@example.test",
        subject="Not a travel operation",
        body_excerpt="This message should be excluded by its mailbox owner.",
        received_at=enabled_at + timedelta(minutes=1),
        relevance_status="possible",
        processing_status="completed",
    )
    db_session.add(message)
    await db_session.flush()
    review = EmailReviewItemModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        message_id=message.id,
        review_type="relevance",
        status="open",
        proposed_action="review_relevance",
        revision=1,
    )
    lease_token = "8" * 32
    analysis = EmailAiAnalysisModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        message_id=message.id,
        status="processing",
        input_hash="7" * 64,
        prompt_schema_version=ai_runtime.EMAIL_AI_SCHEMA_VERSION,
        config_version="v1",
        ai_model="configured-test-model",
        attempt_count=1,
        lease_token=lease_token,
        lease_expires_at=datetime.now(tz=UTC) + timedelta(minutes=2),
    )
    db_session.add_all([review, analysis])
    await db_session.flush()
    claim = ai_runtime.EmailAiClaim(
        analysis_id=analysis.id,
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        message_id=message.id,
        provider_account_id=connection.provider_account_id,
        sync_generation=connection.sync_generation,
        lease_token=lease_token,
    )

    response = await resolve_email_review(
        review_id=review.id,
        payload=ResolveEmailReviewRequest(
            action="mark_unrelated",
            expected_revision=1,
        ),
        current_user=_user(
            owner_id,
            agency_id=agency_id,
            role=UserRole.AGENCY_STAFF,
        ),
        session=db_session,
    )

    await db_session.refresh(message)
    await db_session.refresh(analysis)
    assert response.status == "resolved"
    assert message.relevance_status == "ignored"
    assert message.processing_status == "ignored"
    assert message.evidence_json["human_marked_unrelated"] is True
    assert analysis.status == "ignored"
    assert analysis.last_error_code == "human_marked_unrelated"
    assert analysis.lease_token is None
    assert analysis.lease_expires_at is None
    assert (
        await ai_runtime._load_valid_claim(
            db_session,
            claim,
            for_update=False,
        )
        is None
    )
