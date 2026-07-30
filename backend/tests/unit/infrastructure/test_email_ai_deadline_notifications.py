from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config.settings import Settings
from app.infrastructure.database.email_ai_models import (
    EmailAiAnalysisModel,
    EmailAiRolloutPolicyModel,
    EmailDetectedDeadlineModel,
)
from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailConnectionModel,
    EmailMessageModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    NotificationModel,
    UserModel,
)
from app.infrastructure.email import deadline_notifications


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_secret_key": "test-secret",
        "email_integrations_enabled": True,
        "email_sync_enabled": True,
        "email_ai_enabled": True,
        "email_ai_notifications_enabled": True,
        "email_ai_deadline_notification_window_days": 14,
        "google_api_key": "test-provider-key",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


async def _seed_analysis_graph(
    db_session,
    *,
    now: datetime,
    prefix: str,
):
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    db_session.add(
        AgencyModel(
            id=agency_id,
            name=f"{prefix.title()} Agency",
            email=f"{prefix}-agency@example.test",
            is_active=True,
        )
    )
    db_session.add(
        UserModel(
            id=owner_id,
            email=f"{prefix}-owner@example.test",
            hashed_password="not-used",
            full_name=f"{prefix.title()} Owner",
            role="agency_staff",
            agency_id=agency_id,
            is_active=True,
        )
    )
    await db_session.flush()
    connection = EmailConnectionModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        provider="gmail",
        provider_account_id=f"{prefix}-provider",
        email_address=f"{prefix}-owner@example.test",
        status="active",
        ai_processing_enabled=True,
        ai_enabled_at=now - timedelta(days=1),
        created_by_user_id=owner_id,
    )
    db_session.add(connection)
    await db_session.flush()
    message = EmailMessageModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        provider_message_id=f"{prefix}-message",
        sender_address="supplier@example.test",
        subject="Supplier deadline",
        body_excerpt="Private operational details.",
        received_at=now,
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
        status="completed",
        input_hash="a" * 64,
        prompt_schema_version="email-operations-v1",
        config_version="v1",
        ai_model="configured-test-model",
        ai_provider="google",
        summary="A bounded operational summary.",
        confidence=0.96,
    )
    db_session.add(analysis)
    await db_session.flush()
    return agency_id, owner_id, connection, message, analysis


async def _add_deadline(
    db_session,
    *,
    analysis: EmailAiAnalysisModel,
    due_at: datetime,
    index: int,
    status: str = "detected",
) -> EmailDetectedDeadlineModel:
    deadline = EmailDetectedDeadlineModel(
        agency_id=analysis.agency_id,
        owner_user_id=analysis.owner_user_id,
        connection_id=analysis.connection_id,
        message_id=analysis.message_id,
        analysis_id=analysis.id,
        deadline_type="response_due",
        source_phrase=f"private deadline phrase {index}",
        source_fingerprint=f"{index:064x}",
        source_timezone="UTC",
        due_at=due_at,
        confidence=0.95,
        status=status,
    )
    db_session.add(deadline)
    await db_session.flush()
    return deadline


def _use_shared_session(monkeypatch, db_session) -> None:
    class SharedSessionContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(
        deadline_notifications,
        "AsyncSessionFactory",
        lambda: SharedSessionContext(),
    )


@pytest.mark.asyncio
async def test_deadline_notification_uses_only_current_visible_group_name(
    db_session,
    monkeypatch,
) -> None:
    now = datetime(2026, 7, 30, 8, tzinfo=UTC)
    (
        agency_id,
        owner_id,
        connection,
        _message,
        analysis,
    ) = await _seed_analysis_graph(
        db_session,
        now=now,
        prefix="deadline-group",
    )
    visible_group = ClientGroupModel(
        agency_id=agency_id,
        name="Visible Deadline Group",
        token=f"visible-deadline-{uuid.uuid4().hex}",
        status="active",
        created_by_user_id=owner_id,
    )
    other_owner_id = uuid.uuid4()
    db_session.add(
        UserModel(
            id=other_owner_id,
            email="deadline-hidden-owner@example.test",
            hashed_password="not-used",
            full_name="Deadline Hidden Owner",
            role="agency_staff",
            agency_id=agency_id,
            is_active=True,
        )
    )
    db_session.add(visible_group)
    await db_session.flush()
    hidden_group = ClientGroupModel(
        agency_id=agency_id,
        name="Other Owner Confidential Group",
        token=f"hidden-deadline-{uuid.uuid4().hex}",
        status="active",
        created_by_user_id=other_owner_id,
    )
    db_session.add(hidden_group)
    await db_session.flush()
    analysis.result_json = {"linked_group_id": str(visible_group.id)}
    deadline = await _add_deadline(
        db_session,
        analysis=analysis,
        due_at=now + timedelta(days=5),
        index=91,
    )
    await db_session.flush()
    _use_shared_session(monkeypatch, db_session)

    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=now,
        )
        == 1
    )
    first_notification = (
        await db_session.execute(
            select(NotificationModel).where(
                NotificationModel.type == "email_ai_deadline",
                NotificationModel.user_id == owner_id,
            )
        )
    ).scalar_one()
    assert first_notification.metadata_json["provider"] == "gmail"
    assert first_notification.metadata_json["account_email"] == (
        connection.email_address
    )
    assert first_notification.metadata_json["group_name"] == (
        visible_group.name
    )

    analysis.result_json = {"linked_group_id": str(hidden_group.id)}
    deadline.due_at = deadline.due_at + timedelta(hours=1)
    deadline.updated_at = now + timedelta(minutes=1)
    await db_session.flush()
    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=now,
        )
        == 1
    )
    notifications = list(
        (
            await db_session.execute(
                select(NotificationModel).where(
                    NotificationModel.type == "email_ai_deadline",
                    NotificationModel.user_id == owner_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(notifications) == 2
    assert sum(
        "group_name" in notification.metadata_json
        for notification in notifications
    ) == 1
    assert hidden_group.name not in json.dumps(
        [notification.metadata_json for notification in notifications]
    )


@pytest.mark.asyncio
async def test_deadline_window_scanner_is_owner_scoped_policy_aware_and_idempotent(
    db_session,
    monkeypatch,
) -> None:
    now = datetime(2026, 7, 30, 8, tzinfo=UTC)
    agency_id = uuid.uuid4()
    first_owner = uuid.uuid4()
    second_owner = uuid.uuid4()
    db_session.add(
        AgencyModel(
            id=agency_id,
            name="Deadline Agency",
            email="deadline-agency@example.test",
            is_active=True,
        )
    )
    for owner_id in (first_owner, second_owner):
        db_session.add(
            UserModel(
                id=owner_id,
                email=f"{owner_id}@example.test",
                hashed_password="not-used",
                full_name="Deadline Owner",
                role="agency_staff",
                agency_id=agency_id,
                is_active=True,
            )
        )
    await db_session.flush()

    rows: list[
        tuple[
            EmailConnectionModel,
            EmailMessageModel,
            EmailAiAnalysisModel,
            EmailDetectedDeadlineModel,
        ]
    ] = []
    for index, owner_id in enumerate((first_owner, second_owner), start=1):
        connection = EmailConnectionModel(
            agency_id=agency_id,
            owner_user_id=owner_id,
            provider="gmail",
            provider_account_id=f"deadline-provider-{index}",
            email_address=f"owner-{index}@example.test",
            status="active",
            ai_processing_enabled=True,
            ai_enabled_at=now - timedelta(days=1),
            created_by_user_id=owner_id,
        )
        db_session.add(connection)
        await db_session.flush()
        message = EmailMessageModel(
            agency_id=agency_id,
            owner_user_id=owner_id,
            connection_id=connection.id,
            provider_message_id=f"deadline-message-{index}",
            sender_address="supplier@example.test",
            subject="Private supplier deadline",
            body_excerpt="Confidential deadline body.",
            received_at=now,
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
            status="completed",
            input_hash=str(index) * 64,
            prompt_schema_version="email-operations-v1",
            config_version="v1",
            ai_model="configured-test-model",
            summary="A bounded operational summary.",
            confidence=0.96,
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
            source_phrase="confidential supplier phrase",
            source_fingerprint=str(index + 2) * 64,
            source_timezone="UTC",
            due_at=now + timedelta(days=30),
            confidence=0.95,
            status="detected",
        )
        db_session.add(deadline)
        await db_session.flush()
        rows.append((connection, message, analysis, deadline))

    blocked_policy = EmailAiRolloutPolicyModel(
        agency_id=agency_id,
        owner_user_id=second_owner,
        scope_type="user",
        enabled=False,
        updated_by_user_id=second_owner,
    )
    db_session.add(blocked_policy)
    await db_session.flush()

    _use_shared_session(monkeypatch, db_session)

    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=now,
        )
        == 0
    )
    entered_window = now + timedelta(days=17)
    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=entered_window,
        )
        == 1
    )
    notifications = list(
        (
            await db_session.execute(
                select(NotificationModel).where(NotificationModel.type == "email_ai_deadline")
            )
        )
        .scalars()
        .all()
    )
    assert len(notifications) == 1
    assert notifications[0].user_id == first_owner
    assert notifications[0].entity_id == str(rows[0][1].id)
    serialized_notification = json.dumps(
        {
            "title": notifications[0].title,
            "message": notifications[0].message,
            "metadata": notifications[0].metadata_json,
        }
    ).casefold()
    assert "confidential supplier phrase" not in serialized_notification
    assert "confidential deadline body" not in serialized_notification

    events = list(
        (
            await db_session.execute(
                select(EmailActivityEventModel).where(
                    EmailActivityEventModel.event_type == "ai_deadline_window_notified"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].owner_user_id == first_owner
    assert events[0].changed_entity_id == rows[0][3].id

    notifications[0].is_read = True
    await db_session.flush()
    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=entered_window,
        )
        == 0
    )

    await db_session.delete(blocked_policy)
    await db_session.flush()
    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=entered_window,
        )
        == 1
    )
    owner_ids = set(
        (
            await db_session.execute(
                select(NotificationModel.user_id).where(
                    NotificationModel.type == "email_ai_deadline"
                )
            )
        ).scalars()
    )
    assert owner_ids == {first_owner, second_owner}


@pytest.mark.asyncio
async def test_deadline_scanner_emits_each_stage_once(
    db_session,
    monkeypatch,
) -> None:
    now = datetime(2026, 7, 30, 8, tzinfo=UTC)
    (
        _agency_id,
        _owner_id,
        _connection,
        _message,
        analysis,
    ) = await _seed_analysis_graph(
        db_session,
        now=now,
        prefix="stage-timing",
    )
    due_at = now + timedelta(days=14)
    deadline = await _add_deadline(
        db_session,
        analysis=analysis,
        due_at=due_at,
        index=1,
    )
    _use_shared_session(monkeypatch, db_session)

    stage_times = [
        (now, "ai_deadline_window_notified", "window-notified"),
        (
            due_at - timedelta(hours=24),
            "ai_deadline_24h_notified",
            "24h-notified",
        ),
        (due_at, "ai_deadline_due_notified", "due-notified"),
        (
            due_at + timedelta(hours=24),
            "ai_deadline_overdue_notified",
            "overdue-notified",
        ),
    ]
    for scan_time, _event_type, _event_key_suffix in stage_times:
        assert (
            await deadline_notifications.scan_email_ai_deadline_notifications(
                _settings(),
                now=scan_time,
            )
            == 1
        )
        assert (
            await deadline_notifications.scan_email_ai_deadline_notifications(
                _settings(),
                now=scan_time,
            )
            == 0
        )

    events = list(
        (
            await db_session.execute(
                select(EmailActivityEventModel).where(
                    EmailActivityEventModel.changed_entity_id == deadline.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert {event.event_type for event in events} == {
        event_type for _, event_type, _ in stage_times
    }
    _schedule_epoch, schedule_fingerprint = deadline_notifications._deadline_schedule_identity(
        due_at
    )
    assert {event.event_key for event in events} == {
        (f"email-ai-deadline:{deadline.id}:schedule:{schedule_fingerprint}:{event_key_suffix}")
        for _, _, event_key_suffix in stage_times
    }
    notifications = list(
        (
            await db_session.execute(
                select(NotificationModel).where(NotificationModel.type == "email_ai_deadline")
            )
        )
        .scalars()
        .all()
    )
    assert len(notifications) == 4
    assert {notification.metadata_json["notification_stage"] for notification in notifications} == {
        "window",
        "24h",
        "due",
        "overdue",
    }


@pytest.mark.asyncio
async def test_deadline_stage_notifications_aggregate_per_analysis(
    db_session,
    monkeypatch,
) -> None:
    now = datetime(2026, 7, 30, 8, tzinfo=UTC)
    (
        _agency_id,
        _owner_id,
        _connection,
        _message,
        analysis,
    ) = await _seed_analysis_graph(
        db_session,
        now=now,
        prefix="stage-aggregation",
    )
    imminent_deadlines = [
        await _add_deadline(
            db_session,
            analysis=analysis,
            due_at=now + timedelta(hours=hours),
            index=index,
        )
        for index, hours in ((1, 6), (2, 12))
    ]
    due_deadline = await _add_deadline(
        db_session,
        analysis=analysis,
        due_at=now - timedelta(hours=2),
        index=3,
    )
    _use_shared_session(monkeypatch, db_session)

    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=now,
        )
        == 2
    )
    notifications = list(
        (
            await db_session.execute(
                select(NotificationModel).where(NotificationModel.type == "email_ai_deadline")
            )
        )
        .scalars()
        .all()
    )
    by_stage = {
        notification.metadata_json["notification_stage"]: notification
        for notification in notifications
    }
    assert set(by_stage) == {"24h", "due"}
    assert by_stage["24h"].metadata_json["deadline_count"] == 2
    assert set(by_stage["24h"].metadata_json["deadline_ids"]) == {
        str(deadline.id) for deadline in imminent_deadlines
    }
    assert by_stage["due"].metadata_json["deadline_count"] == 1
    assert by_stage["due"].metadata_json["deadline_ids"] == [str(due_deadline.id)]
    events = list(
        (
            await db_session.execute(
                select(EmailActivityEventModel).where(
                    EmailActivityEventModel.changed_entity_type == "email_detected_deadline"
                )
            )
        )
        .scalars()
        .all()
    )
    assert sum(event.event_type == "ai_deadline_24h_notified" for event in events) == 2
    assert sum(event.event_type == "ai_deadline_due_notified" for event in events) == 1

    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=now,
        )
        == 0
    )
    assert (
        await db_session.execute(
            select(NotificationModel).where(NotificationModel.type == "email_ai_deadline")
        )
    ).scalars().all() == notifications


@pytest.mark.asyncio
async def test_initial_analysis_coverage_suppresses_immediate_24h_then_due_fires(
    db_session,
    monkeypatch,
) -> None:
    now = datetime(2026, 7, 30, 8, tzinfo=UTC)
    (
        _agency_id,
        _owner_id,
        connection,
        message,
        analysis,
    ) = await _seed_analysis_graph(
        db_session,
        now=now,
        prefix="initial-coverage",
    )
    deadline = await _add_deadline(
        db_session,
        analysis=analysis,
        due_at=now + timedelta(hours=12),
        index=1,
    )
    row = (deadline, analysis, message, connection)

    assert (
        await deadline_notifications.mark_initial_deadline_window_coverage(
            db_session,
            rows=[row],
            now=now,
            window_days=14,
        )
        == 2
    )
    initial_events = list(
        (
            await db_session.execute(
                select(EmailActivityEventModel).where(
                    EmailActivityEventModel.changed_entity_id == deadline.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert {event.event_type for event in initial_events} == {
        "ai_deadline_window_notified",
        "ai_deadline_24h_notified",
    }
    assert {event.details["notification_mode"] for event in initial_events} == {
        "analysis_attention"
    }

    _use_shared_session(monkeypatch, db_session)
    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=now,
        )
        == 0
    )
    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=deadline.due_at,
        )
        == 1
    )
    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=deadline.due_at,
        )
        == 0
    )
    overdue_time = deadline.due_at + timedelta(hours=24)
    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=overdue_time,
        )
        == 1
    )
    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=overdue_time,
        )
        == 0
    )
    event_types = set(
        (
            await db_session.execute(
                select(EmailActivityEventModel.event_type).where(
                    EmailActivityEventModel.changed_entity_id == deadline.id
                )
            )
        ).scalars()
    )
    assert event_types == {
        "ai_deadline_window_notified",
        "ai_deadline_24h_notified",
        "ai_deadline_due_notified",
        "ai_deadline_overdue_notified",
    }
    notifications = list(
        (
            await db_session.execute(
                select(NotificationModel).where(NotificationModel.type == "email_ai_deadline")
            )
        )
        .scalars()
        .all()
    )
    assert {notification.metadata_json["notification_stage"] for notification in notifications} == {
        "due",
        "overdue",
    }


@pytest.mark.asyncio
async def test_corrected_due_date_gets_fresh_schedule_stage_once(
    db_session,
    monkeypatch,
) -> None:
    now = datetime(2026, 7, 30, 8, tzinfo=UTC)
    (
        _agency_id,
        _owner_id,
        _connection,
        _message,
        analysis,
    ) = await _seed_analysis_graph(
        db_session,
        now=now,
        prefix="schedule-correction",
    )
    original_due_at = now + timedelta(days=5)
    deadline = await _add_deadline(
        db_session,
        analysis=analysis,
        due_at=original_due_at,
        index=1,
    )
    _use_shared_session(monkeypatch, db_session)

    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=now,
        )
        == 1
    )
    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=now,
        )
        == 0
    )

    corrected_at = now + timedelta(minutes=1)
    corrected_due_at = now + timedelta(days=10)
    deadline.due_at = corrected_due_at
    deadline.updated_at = corrected_at
    await db_session.flush()

    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=corrected_at,
        )
        == 1
    )
    assert (
        await deadline_notifications.scan_email_ai_deadline_notifications(
            _settings(),
            now=corrected_at,
        )
        == 0
    )

    events = list(
        (
            await db_session.execute(
                select(EmailActivityEventModel)
                .where(
                    EmailActivityEventModel.changed_entity_id == deadline.id,
                    EmailActivityEventModel.event_type == "ai_deadline_window_notified",
                )
                .order_by(EmailActivityEventModel.occurred_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 2
    original_identity = deadline_notifications._deadline_schedule_identity(original_due_at)
    corrected_identity = deadline_notifications._deadline_schedule_identity(corrected_due_at)
    assert original_identity != corrected_identity
    assert {event.details["schedule_epoch"] for event in events} == {
        original_identity[0],
        corrected_identity[0],
    }
    assert {event.details["schedule_fingerprint"] for event in events} == {
        original_identity[1],
        corrected_identity[1],
    }
    assert {event.event_key for event in events} == {
        (f"email-ai-deadline:{deadline.id}:schedule:{original_identity[1]}:window-notified"),
        (f"email-ai-deadline:{deadline.id}:schedule:{corrected_identity[1]}:window-notified"),
    }

    notifications = list(
        (
            await db_session.execute(
                select(NotificationModel).where(NotificationModel.type == "email_ai_deadline")
            )
        )
        .scalars()
        .all()
    )
    assert len(notifications) == 2
    assert len({notification.dedupe_key for notification in notifications}) == 2
    assert {
        notification.metadata_json["deadline_schedule_fingerprints"][str(deadline.id)]
        for notification in notifications
    } == {original_identity[1], corrected_identity[1]}


@pytest.mark.asyncio
async def test_deadline_window_scanner_stays_dormant_when_notifications_are_off(
    monkeypatch,
) -> None:
    session_factory_called = False

    def session_factory():
        nonlocal session_factory_called
        session_factory_called = True
        raise AssertionError("database must not be opened while disabled")

    monkeypatch.setattr(
        deadline_notifications,
        "AsyncSessionFactory",
        session_factory,
    )
    result = await deadline_notifications.scan_email_ai_deadline_notifications(
        _settings(email_ai_notifications_enabled=False)
    )

    assert result == 0
    assert session_factory_called is False
